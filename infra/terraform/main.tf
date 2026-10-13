locals {
  repository_root = abspath("${path.module}/../..")
  source_files = sort(concat(
    ["Dockerfile", "Makefile", ".dockerignore"],
    tolist(fileset(local.repository_root, "src/*.cob")),
    tolist(fileset(local.repository_root, "copybooks/*.cpy")),
    tolist(fileset(local.repository_root, "native/*.c")),
    tolist(fileset(local.repository_root, "tools/*.py")),
    tolist(fileset(local.repository_root, "web/**"))
  ))
  source_digest = sha256(join("", [for file in local.source_files : filesha256("${local.repository_root}/${file}")]))
}

resource "docker_image" "meridian" {
  name         = "${var.name}:managed"
  keep_locally = true
  build {
    context    = local.repository_root
    dockerfile = "Dockerfile"
    tag        = ["${var.name}:managed"]
  }
  triggers = {
    source = local.source_digest
  }
}

resource "docker_network" "service" {
  name     = "${var.name}-network"
  driver   = "bridge"
  internal = false
}

resource "docker_volume" "journal" {
  name = "${var.name}-journal"
  lifecycle {
    prevent_destroy = true
  }
}

resource "docker_container" "meridian" {
  name           = var.name
  image          = docker_image.meridian.image_id
  user           = "10001:10001"
  read_only      = true
  restart        = "unless-stopped"
  memory         = var.memory_mb
  remove_volumes = false
  wait           = true
  wait_timeout   = 90
  security_opts  = ["no-new-privileges:true"]
  tmpfs          = { "/tmp" = "rw,noexec,nosuid,size=16m,mode=1777" }
  env            = ["MERIDIAN_API_TOKEN=${var.api_token}", "MERIDIAN_DATA_DIR=/data"]
  log_driver     = "json-file"
  log_opts       = { "max-size" = "5m", "max-file" = "3" }

  capabilities {
    drop = ["ALL"]
  }
  ports {
    internal = 8080
    external = var.host_port
    ip       = "127.0.0.1"
  }
  networks_advanced {
    name = docker_network.service.name
  }
  volumes {
    volume_name    = docker_volume.journal.name
    container_path = "/data"
    read_only      = false
  }

  labels {
    label = "com.meridian.managed-by"
    value = "terraform"
  }
}
