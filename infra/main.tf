# Azure resources for the PriceCatcher lake (step 7, option A).
#
# Creates, in one resource group:
#   - a storage account with a hierarchical namespace (ADLS Gen2)
#   - two containers: landing (raw files) and lake (Delta tables)
#   - read/write access to that storage for whoever runs `terraform apply`
#   - a monthly budget that emails you at 80% and 100% of the limit
#
# Run from WSL after `az login`; see infra/README.md.

terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  # Use Azure AD (az login) rather than storage account keys for containers.
  storage_use_azuread = true
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "main" {
  name     = "rg-pricecatcher"
  location = var.location
  tags     = local.tags
}

# Storage account names are global across Azure, so add a random suffix.
resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_storage_account" "lake" {
  name                            = "stpricecatcher${random_string.suffix.result}"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS" # one copy set in one region: cheapest; data can be re-downloaded
  account_kind                    = "StorageV2"
  is_hns_enabled                  = true # this is what makes it ADLS Gen2 (real folders)
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false # logins only, no long-lived keys
  tags                            = local.tags
}

# Let the person running Terraform read and write blobs (Azure roles take a
# few minutes to apply after the first run).
resource "azurerm_role_assignment" "me_blob_contributor" {
  scope                = azurerm_storage_account.lake.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_storage_container" "containers" {
  for_each              = toset(["landing", "lake"])
  name                  = each.key
  storage_account_id    = azurerm_storage_account.lake.id
  container_access_type = "private"
  depends_on            = [azurerm_role_assignment.me_blob_contributor]
}

resource "azurerm_consumption_budget_subscription" "monthly" {
  name            = "budget-pricecatcher"
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = var.budget_usd
  time_grain      = "Monthly"

  time_period {
    # Azure needs the first day of a month; start with the current one.
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = [var.alert_email]
  }

  lifecycle {
    ignore_changes = [time_period] # timestamp() changes every run
  }
}

locals {
  tags = {
    project = "pricecatcher"
    managed = "terraform"
  }
}
