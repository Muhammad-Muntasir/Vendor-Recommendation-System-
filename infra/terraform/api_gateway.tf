###############################################################################
# API Gateway — REST API with Cognito Authorizer and CORS
###############################################################################

resource "aws_api_gateway_rest_api" "ai_vrs" {
  name        = "ai-vrs-api"
  description = "AI Vendor Recommendation System REST API"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = { Name = "ai-vrs-api" }
}

# ---------------------------------------------------------------------------
# Cognito Authorizer
# ---------------------------------------------------------------------------
resource "aws_api_gateway_authorizer" "cognito" {
  name            = "ai-vrs-cognito-authorizer"
  rest_api_id     = aws_api_gateway_rest_api.ai_vrs.id
  type            = "COGNITO_USER_POOLS"
  identity_source = "method.request.header.Authorization"
  provider_arns   = [aws_cognito_user_pool.ai_vrs.arn]
}

# ---------------------------------------------------------------------------
# Proxy resource — catch-all {proxy+}
# ---------------------------------------------------------------------------
resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.ai_vrs.id
  parent_id   = aws_api_gateway_rest_api.ai_vrs.root_resource_id
  path_part   = "{proxy+}"
}

# ANY method on {proxy+} — protected by Cognito
resource "aws_api_gateway_method" "proxy_any" {
  rest_api_id   = aws_api_gateway_rest_api.ai_vrs.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "ANY"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "proxy_any" {
  rest_api_id             = aws_api_gateway_rest_api.ai_vrs.id
  resource_id             = aws_api_gateway_resource.proxy.id
  http_method             = aws_api_gateway_method.proxy_any.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.ai_vrs.invoke_arn
}

# OPTIONS on {proxy+} — CORS preflight (no auth)
resource "aws_api_gateway_method" "proxy_options" {
  rest_api_id   = aws_api_gateway_rest_api.ai_vrs.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "proxy_options" {
  rest_api_id = aws_api_gateway_rest_api.ai_vrs.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method
  type        = "MOCK"
  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_method_response" "proxy_options_200" {
  rest_api_id = aws_api_gateway_rest_api.ai_vrs.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "proxy_options_200" {
  rest_api_id = aws_api_gateway_rest_api.ai_vrs.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method
  status_code = aws_api_gateway_method_response.proxy_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Authorization,Content-Type'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,POST,OPTIONS'"
    # Explicit allowed origin — no wildcard in production
    "method.response.header.Access-Control-Allow-Origin" = "'${var.allowed_cors_origin}'"
  }

  depends_on = [aws_api_gateway_integration.proxy_options]
}

# ---------------------------------------------------------------------------
# Root resource — ANY + OPTIONS
# ---------------------------------------------------------------------------
resource "aws_api_gateway_method" "root_any" {
  rest_api_id   = aws_api_gateway_rest_api.ai_vrs.id
  resource_id   = aws_api_gateway_rest_api.ai_vrs.root_resource_id
  http_method   = "ANY"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "root_any" {
  rest_api_id             = aws_api_gateway_rest_api.ai_vrs.id
  resource_id             = aws_api_gateway_rest_api.ai_vrs.root_resource_id
  http_method             = aws_api_gateway_method.root_any.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.ai_vrs.invoke_arn
}

# ---------------------------------------------------------------------------
# Deployment and Stage
# ---------------------------------------------------------------------------
resource "aws_api_gateway_deployment" "ai_vrs" {
  rest_api_id = aws_api_gateway_rest_api.ai_vrs.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.proxy.id,
      aws_api_gateway_method.proxy_any.id,
      aws_api_gateway_integration.proxy_any.id,
      aws_api_gateway_method.proxy_options.id,
      aws_api_gateway_integration.proxy_options.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.proxy_any,
    aws_api_gateway_integration.proxy_options,
    aws_api_gateway_integration.root_any,
  ]
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.ai_vrs.id
  rest_api_id   = aws_api_gateway_rest_api.ai_vrs.id
  stage_name    = "prod"

  tags = { Name = "ai-vrs-api-prod" }
}
