# AWS resources for the copilot: DynamoDB tables, a Bedrock Guardrail, and a
# least-privilege IAM policy for the app's runtime role (ECS task / App Runner).
# The Knowledge Base itself is created in the console or with the
# aws_bedrockagent_knowledge_base resource once its vector store exists.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.70" }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "support-copilot"
}

variable "knowledge_base_arn" {
  type        = string
  description = "ARN of the Bedrock Knowledge Base to allow Retrieve on (leave empty to skip)"
  default     = ""
}

resource "aws_dynamodb_table" "sessions" {
  name         = "${var.project}-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery { enabled = true }
}

resource "aws_dynamodb_table" "orders" {
  name         = "${var.project}-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "order_id"

  attribute {
    name = "order_id"
    type = "S"
  }
}

resource "aws_bedrock_guardrail" "support" {
  name                      = "${var.project}-guardrail"
  blocked_input_messaging   = "Sorry, I can't help with that request."
  blocked_outputs_messaging = "Sorry, I can't share that. Let me connect you with a support specialist."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "MEDIUM"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "MEDIUM"
      output_strength = "HIGH"
    }
  }

  sensitive_information_policy_config {
    pii_entities_config {
      type   = "CREDIT_DEBIT_CARD_NUMBER"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
  }

  topic_policy_config {
    topics_config {
      name       = "competitor-pricing"
      type       = "DENY"
      definition = "Comparisons with or pricing of competitor products and stores."
      examples   = ["Is Best Buy cheaper than you?"]
    }
  }
}

resource "aws_bedrock_guardrail_version" "v1" {
  guardrail_arn = aws_bedrock_guardrail.support.guardrail_arn
  description   = "Initial version"
}

data "aws_iam_policy_document" "app" {
  statement {
    sid       = "InvokeClaude"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock-mantle:*"]
    resources = ["*"]
  }

  statement {
    sid       = "ApplyGuardrail"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.support.guardrail_arn]
  }

  dynamic "statement" {
    for_each = var.knowledge_base_arn == "" ? [] : [1]
    content {
      sid       = "RetrieveKnowledge"
      actions   = ["bedrock:Retrieve"]
      resources = [var.knowledge_base_arn]
    }
  }

  statement {
    sid       = "SessionsAndOrders"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem"]
    resources = [aws_dynamodb_table.sessions.arn, aws_dynamodb_table.orders.arn]
  }
}

resource "aws_iam_policy" "app" {
  name   = "${var.project}-runtime"
  policy = data.aws_iam_policy_document.app.json
}

output "env" {
  description = "Environment variables for the app"
  value = {
    COPILOT_MODE      = "bedrock"
    AWS_REGION        = var.region
    SESSIONS_TABLE    = aws_dynamodb_table.sessions.name
    ORDERS_TABLE      = aws_dynamodb_table.orders.name
    GUARDRAIL_ID      = aws_bedrock_guardrail.support.guardrail_id
    GUARDRAIL_VERSION = aws_bedrock_guardrail_version.v1.version
  }
}

output "runtime_policy_arn" {
  value = aws_iam_policy.app.arn
}
