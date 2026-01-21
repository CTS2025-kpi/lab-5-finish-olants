variable "n8n_sns_endpoint" {
  type    = string
  default = "https://n8n-olants.pp.ua/webhook/aws/sns/alarms"
}

resource "aws_sns_topic" "alarms" {
  name = "${local.name}-alarms"
}

# Allow CloudWatch to publish to this topic
data "aws_iam_policy_document" "sns_topic_policy" {
  statement {
    sid     = "AllowCloudWatchPublish"
    effect  = "Allow"
    actions = ["SNS:Publish"]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    resources = [aws_sns_topic.alarms.arn]
  }
}

resource "aws_sns_topic_policy" "alarms" {
  arn    = aws_sns_topic.alarms.arn
  policy = data.aws_iam_policy_document.sns_topic_policy.json
}
