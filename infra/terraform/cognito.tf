###############################################################################
# Cognito User Pool and App Client — AI Vendor Recommendation System
###############################################################################

resource "aws_cognito_user_pool" "ai_vrs" {
  name = "ai-vrs-user-pool"

  # Self-registration enabled, email verification required
  auto_verified_attributes = ["email"]

  username_attributes = ["email"]

  # Password policy: min 8 chars, upper, lower, digit, special
  password_policy {
    minimum_length                   = 8
    require_uppercase                = true
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  # Email verification
  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "RetailFixIt — Verify your email"
    email_message        = "Your verification code is {####}"
  }

  # Post-Confirmation Lambda trigger
  lambda_config {
    post_confirmation = aws_lambda_function.ai_vrs.arn
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
    string_attribute_constraints {
      min_length = 5
      max_length = 254
    }
  }

  tags = { Name = "ai-vrs-user-pool" }
}

resource "aws_cognito_user_pool_client" "ai_vrs" {
  name         = "ai-vrs-app-client"
  user_pool_id = aws_cognito_user_pool.ai_vrs.id

  # No client secret — SPA
  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH",
  ]

  # Token validity
  access_token_validity  = var.cognito_access_token_validity  # hours
  refresh_token_validity = var.cognito_refresh_token_validity # days

  token_validity_units {
    access_token  = "hours"
    refresh_token = "days"
  }

  prevent_user_existence_errors = "ENABLED"
}
