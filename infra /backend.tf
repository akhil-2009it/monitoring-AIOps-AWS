terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.30"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.24"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Remote state — S3 + DynamoDB lock
  # NEVER run terraform without this backend. Local state is forbidden.
  # Bucket is pre-created via bootstrap (see scripts/bootstrap_state.sh)
  backend "s3" {
    bucket         = "mlops-learning-tfstate"
    key            = "mlops-learning/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "mlops-learning-tfstate-lock"
    encrypt        = true
  }
}
