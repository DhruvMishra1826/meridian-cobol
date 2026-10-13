output "console_url" {
  description = "Local console URL; API requests require the configured bearer token."
  value       = "http://127.0.0.1:${var.host_port}"
}

output "container_name" {
  description = "Container name for logs, journal export and operator checks."
  value       = docker_container.meridian.name
}

output "journal_volume" {
  description = "Protected named volume retaining business records across container replacement."
  value       = docker_volume.journal.name
}

output "source_digest" {
  description = "Build-input digest causing image replacement when application sources change."
  value       = local.source_digest
}
