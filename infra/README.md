# Azure infrastructure (Terraform)

Creates everything the cloud version of the pipeline needs, from code:

| Resource | Name | Why |
|---|---|---|
| Resource group | `rg-pricecatcher` | One folder in Azure for this project; delete it to remove everything |
| Storage account (ADLS Gen2) | `stpricecatcher<random>` | Holds the raw files and the Delta tables |
| Containers | `landing`, `lake` | Same split as `data/landing/` and `lake/` locally |
| Role assignment | Storage Blob Data Contributor | Lets you (whoever runs Terraform) read and write the storage |
| Budget | `budget-pricecatcher` | Emails you at 80% of US$5 spent, or when the month is forecast to pass US$5 |

Expected cost: a few cents a month for storage (the data is well under 1 GB).

## First run (WSL)

1. Install the Azure CLI and Terraform:

   ```bash
   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
   wget -O - https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
   echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
   sudo apt update && sudo apt install -y terraform
   ```

2. Log in (prints a code to enter in your Windows browser):

   ```bash
   az login --use-device-code
   az account show --query id -o tsv     # your subscription ID
   ```

3. Fill in your settings:

   ```bash
   cd infra
   cp terraform.tfvars.example terraform.tfvars
   nano terraform.tfvars                 # subscription ID and your email
   ```

4. Create the resources:

   ```bash
   terraform init
   terraform plan      # shows what will be created; nothing changes yet
   terraform apply     # type yes
   ```

5. `terraform output` prints the storage account name and the `abfss://`
   paths the pipeline will use.

`terraform.tfvars` and `terraform.tfstate` stay on your laptop and are not
committed. The state file is Terraform's record of what it created; keep it.

To remove everything: `terraform destroy`.
