output "storage_account" {
  value = azurerm_storage_account.lake.name
}

output "lake_root" {
  description = "Value for LAKE_ROOT when the pipeline writes to Azure"
  value       = "abfss://lake@${azurerm_storage_account.lake.name}.dfs.core.windows.net"
}

output "landing_root" {
  value = "abfss://landing@${azurerm_storage_account.lake.name}.dfs.core.windows.net"
}
