variable "subscription_id" {
  description = "Azure subscription ID (az account show --query id -o tsv)"
  type        = string
}

variable "alert_email" {
  description = "Where budget alerts are sent"
  type        = string
}

variable "location" {
  description = "Azure region. southeastasia is Singapore, the closest full region to Malaysia."
  type        = string
  default     = "southeastasia"
}

variable "budget_usd" {
  description = "Monthly budget; alerts at 80% actual and 100% forecast"
  type        = number
  default     = 5
}
