#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE
#define _DEFAULT_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

/* COBOL owns validation and business state. This adapter owns POSIX durability.
 * A locked journal is the sole source of truth. CRC chaining detects accidental
 * corruption; it is deliberately not presented as cryptographic authentication.
 */
static int journal_fd = -1;
static FILE *reader;
static uint32_t chain;
static unsigned long sequence;
static const char header[] = "MERIDIAN-JOURNAL-1\n";

static uint32_t checksum(uint32_t previous, const unsigned char *data, size_t n) {
    uint32_t crc = ~previous;
    for (size_t i = 0; i < n; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xedb88320u & (uint32_t)-(int)(crc & 1u));
    }
    return ~crc;
}

static int write_all(int fd, const void *buffer, size_t n) {
    const unsigned char *p = buffer;
    while (n) {
        ssize_t wrote = write(fd, p, n);
        if (wrote < 0 && errno == EINTR) continue;
        if (wrote <= 0) return -1;
        p += wrote;
        n -= (size_t)wrote;
    }
    return 0;
}

int md_store_close(void) {
    if (reader) { fclose(reader); reader = NULL; }
    if (journal_fd >= 0) { close(journal_fd); journal_fd = -1; }
    return 0;
}

int md_store_open(const char *path, int length) {
    struct stat info;
    char filename[1024], line[64];
    if (length < 1 || length >= (int)sizeof filename) return -1;
    memcpy(filename, path, (size_t)length);
    filename[length] = 0;
    journal_fd = open(filename, O_RDWR | O_CREAT | O_NOFOLLOW, 0600);
    if (journal_fd < 0) return -2;
    if (flock(journal_fd, LOCK_EX) < 0) { md_store_close(); return -3; }
    if (fstat(journal_fd, &info) < 0 || !S_ISREG(info.st_mode)) {
        md_store_close(); return -4;
    }
    if (info.st_size == 0) {
        if (write_all(journal_fd, header, sizeof header - 1) || fsync(journal_fd)) {
            md_store_close(); return -5;
        }
        /* Persist initial directory entry as well as the new file's bytes. */
        char parent[1024];
        memcpy(parent, filename, (size_t)length + 1);
        char *slash = strrchr(parent, '/');
        if (slash) { if (slash == parent) slash[1] = 0; else *slash = 0; }
        else strcpy(parent, ".");
        int directory_fd = open(parent, O_RDONLY);
        if (directory_fd < 0 || fsync(directory_fd)) {
            if (directory_fd >= 0) close(directory_fd);
            md_store_close(); return -5;
        }
        close(directory_fd);
    } else {
        char last;
        if (pread(journal_fd, &last, 1, info.st_size - 1) != 1 || last != '\n') {
            md_store_close(); return -6;
        }
    }
    int read_fd = dup(journal_fd);
    if (read_fd < 0) { md_store_close(); return -7; }
    if (lseek(read_fd, 0, SEEK_SET) < 0 || !(reader = fdopen(read_fd, "r"))) {
        close(read_fd); md_store_close(); return -7;
    }
    if (!fgets(line, sizeof line, reader) || strcmp(line, header)) {
        md_store_close(); return -8;
    }
    chain = 0;
    sequence = 0;
    return 0;
}

int md_store_next(char *buffer, int capacity) {
    char line[4200];
    if (!reader || capacity < 1 || capacity > 4096) return -1;
    if (!fgets(line, sizeof line, reader)) return ferror(reader) ? -2 : 0;
    size_t size = strlen(line);
    if (size < 20 || line[size - 1] != '\n' || line[8] != '|' || line[17] != '|')
        return -3;
    for (int i = 0; i < 17; ++i)
        if (i != 8 && !strchr("0123456789ABCDEF", line[i])) return -3;
    line[size - 1] = 0;
    unsigned stored_sequence, stored_crc;
    int consumed = 0;
    if (sscanf(line, "%8X|%8X|%n", &stored_sequence, &stored_crc, &consumed) != 2
        || consumed != 18 || stored_sequence != sequence + 1) return -4;
    size_t payload_length = size - 19;
    if (payload_length > (size_t)capacity || !payload_length) return -5;
    uint32_t actual = checksum(chain, (const unsigned char *)line + 18, payload_length);
    if (actual != stored_crc) return -6;
    for (size_t i = 18; i < size - 1; ++i)
        if ((unsigned char)line[i] < 32 || (unsigned char)line[i] > 126) return -7;
    memset(buffer, ' ', (size_t)capacity);
    memcpy(buffer, line + 18, payload_length);
    chain = actual;
    sequence++;
    return (int)payload_length;
}

int md_store_append(const char *buffer, int length) {
    char prefix[32];
    if (journal_fd < 0 || length < 1 || length > 4096 || sequence >= 0xffffffffu) return -1;
    for (int i = 0; i < length; ++i)
        if ((unsigned char)buffer[i] < 32 || (unsigned char)buffer[i] > 126) return -2;
    off_t original_size = lseek(journal_fd, 0, SEEK_END);
    if (original_size < 0) return -3;
    uint32_t next = checksum(chain, (const unsigned char *)buffer, (size_t)length);
    int size = snprintf(prefix, sizeof prefix, "%08lX|%08X|", sequence + 1, next);
    if (write_all(journal_fd, prefix, (size_t)size)
        || write_all(journal_fd, buffer, (size_t)length)
        || write_all(journal_fd, "\n", 1) || fsync(journal_fd)) {
        /* Failed operations are never acknowledged. A failed rollback requires
         * restore/inspection; subsequent startup will refuse a truncated tail. */
        if (ftruncate(journal_fd, original_size) || fsync(journal_fd)) return -5;
        return -4;
    }
    chain = next;
    sequence++;
    return 0;
}
