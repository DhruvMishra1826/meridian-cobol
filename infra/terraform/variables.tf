variable "docker_host" {
  description = "Local Docker Engine Unix socket; use the same endpoint for DOCKER_HOST when building images."
  type        = string
  default     = "unix:///var/run/docker.sock"
  validation {
    condition     = startswith(var.docker_host, "unix:///")
    error_message = "This local deployment module requires a Unix socket; network daemon exposure is unsupported."
  }
}

variable "name" {
  description = "Unique prefix for the container, network and persistent journal volume."
  type        = string
  default     = "meridian"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.name))
    error_message = "Name must have 3..40 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "host_port" {
  description = "Loopback-only published HTTP port; place remote access behind a separately managed TLS proxy."
  type        = number
  default     = 8080
  validation {
    condition     = var.host_port == floor(var.host_port) && var.host_port >= 1024 && var.host_port <= 65535
    error_message = "Use an integer unprivileged port between 1024 and 65535."
  }
}

variable "api_token" {
  description = "Bearer token supplied through TF_VAR_api_token. Terraform state contains this sensitive value."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[!-~]{32,}$", var.api_token))
    error_message = "Generate a token with at least 32 printable ASCII characters and no whitespace."
  }
}

variable "memory_mb" {
  description = "Container memory ceiling in MiB; includes concurrent short-lived COBOL processes."
  type        = number
  default     = 256
  validation {
    condition     = var.memory_mb == floor(var.memory_mb) && var.memory_mb >= 128 && var.memory_mb <= 4096
    error_message = "Memory must be an integer from 128 through 4096 MiB."
  }
}
