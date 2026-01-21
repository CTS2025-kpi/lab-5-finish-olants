terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }

  # Optional remote state (recommended):
  # backend "s3" {
  #   bucket         = "your-tf-state-bucket"
  #   key            = "sharded-lab/terraform.tfstate"
  #   region         = "eu-central-1"
  #   dynamodb_table = "your-tf-locks"
  #   encrypt        = true
  # }
}
