output "alb_dns_name" { value = aws_lb.app.dns_name }
output "rds_endpoint" { value = aws_db_instance.postgres.address }
output "redis_endpoint" { value = aws_elasticache_cluster.redis.cache_nodes[0].address }
output "sync_queue_url" { value = aws_sqs_queue.sync.url }
output "artifacts_bucket" { value = aws_s3_bucket.artifacts.bucket }
