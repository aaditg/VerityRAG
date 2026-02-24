variable "aws_region" { type = string default = "us-east-1" }
variable "db_username" { type = string default = "postgres" }
variable "db_password" { type = string sensitive = true }
variable "db_name" { type = string default = "rag" }
variable "artifacts_bucket_name" { type = string default = "rag-mvp-artifacts" }
variable "api_image" { type = string default = "public.ecr.aws/docker/library/python:3.12-slim" }
variable "worker_image" { type = string default = "public.ecr.aws/docker/library/python:3.12-slim" }
