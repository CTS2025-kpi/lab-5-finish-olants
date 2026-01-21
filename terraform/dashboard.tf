resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      # -------------------- Coordinator latency (avg/p50/p95/p99) — all routes --------------------
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            [
              {
                id         = "e_avg"
                label      = "avg"
                expression = "SEARCH('{ShardedKV,Cluster,Service,Route,Method} MetricName=\"RequestLatencyMs\" Cluster=\"${local.name}\" Service=\"coordinator\"', 'Average', 60)"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "e_p50"
                label      = "p50"
                expression = "SEARCH('{ShardedKV,Cluster,Service,Route,Method} MetricName=\"RequestLatencyMs\" Cluster=\"${local.name}\" Service=\"coordinator\"', 'p50', 60)"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "e_p95"
                label      = "p95"
                expression = "SEARCH('{ShardedKV,Cluster,Service,Route,Method} MetricName=\"RequestLatencyMs\" Cluster=\"${local.name}\" Service=\"coordinator\"', 'p95', 60)"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "e_p99"
                label      = "p99"
                expression = "SEARCH('{ShardedKV,Cluster,Service,Route,Method} MetricName=\"RequestLatencyMs\" Cluster=\"${local.name}\" Service=\"coordinator\"', 'p99', 60)"
                region     = var.aws_region
              }
            ]
          ]
          period = 60
          region = var.aws_region
          title  = "Coordinator latency (avg/p50/p95/p99) — all routes"
          view   = "timeSeries"
        }
      },

      # -------------------- Throughput (RequestCount) collapsed to 2 lines --------------------
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          region = var.aws_region
          title  = "Request count (throughput) — total"
          period = 60
          view   = "timeSeries"
          metrics = [
            # coordinator totals across all routes/methods
            [
              {
                id         = "c_cnt_series"
                expression = "REMOVE_EMPTY(SEARCH('{ShardedKV,Cluster,Service,Route,Method} MetricName=\"RequestCount\" Cluster=\"${local.name}\" Service=\"coordinator\"', 'Sum', 60))"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "c_cnt_total"
                label      = "coordinator req/min (sum)"
                expression = "SUM(METRICS(c_cnt_series))"
                region     = var.aws_region
              }
            ],

            # shards totals across all shards/routes/methods
            [
              {
                id         = "s_cnt_series"
                expression = "REMOVE_EMPTY(SEARCH('{ShardedKV,Cluster,Service,Route,Method} MetricName=\"RequestCount\" Cluster=\"${local.name}\" Service=\"shard\"', 'Sum', 60))"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "s_cnt_total"
                label      = "shards req/min (sum)"
                expression = "SUM(METRICS(s_cnt_series))"
                region     = var.aws_region
              }
            ]
          ]
        }
      },

      # -------------------- 5xx errors collapsed to 2 lines --------------------
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          region = var.aws_region
          title  = "5xx errors — total"
          period = 60
          view   = "timeSeries"
          metrics = [
            # coordinator
            [
              {
                id         = "c_5xx_series"
                expression = "REMOVE_EMPTY(SEARCH('{ShardedKV,Cluster,Service,Route,Method} MetricName=\"Request5xx\" Cluster=\"${local.name}\" Service=\"coordinator\"', 'Sum', 60))"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "c_5xx_total"
                label      = "coordinator 5xx/min (sum)"
                expression = "SUM(METRICS(c_5xx_series))"
                region     = var.aws_region
              }
            ],

            # shards
            [
              {
                id         = "s_5xx_series"
                expression = "REMOVE_EMPTY(SEARCH('{ShardedKV,Cluster,Service,Route,Method} MetricName=\"Request5xx\" Cluster=\"${local.name}\" Service=\"shard\"', 'Sum', 60))"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "s_5xx_total"
                label      = "shards 5xx/min (sum)"
                expression = "SUM(METRICS(s_5xx_series))"
                region     = var.aws_region
              }
            ]
          ]
        }
      },

      # -------------------- Replication lag collapsed to 4 lines (avg/p50/p95/p99) --------------------
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          region = var.aws_region
          title  = "Replication lag (avg/p50/p95/p99) — all shards"
          period = 60
          view   = "timeSeries"
          metrics = [
            [
              {
                id         = "lag_avg_series"
                expression = "REMOVE_EMPTY(SEARCH('{ShardedKV,Cluster,Service,Shard} MetricName=\"ReplicationLagMs\" Cluster=\"${local.name}\" Service=\"shard\"', 'Average', 60))"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "lag_avg"
                label      = "avg"
                expression = "AVG(METRICS(lag_avg_series))"
                region     = var.aws_region
              }
            ],

            [
              {
                id         = "lag_p50_series"
                expression = "REMOVE_EMPTY(SEARCH('{ShardedKV,Cluster,Service,Shard} MetricName=\"ReplicationLagMs\" Cluster=\"${local.name}\" Service=\"shard\"', 'p50', 60))"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "lag_p50"
                label      = "p50"
                expression = "AVG(METRICS(lag_p50_series))"
                region     = var.aws_region
              }
            ],

            [
              {
                id         = "lag_p95_series"
                expression = "REMOVE_EMPTY(SEARCH('{ShardedKV,Cluster,Service,Shard} MetricName=\"ReplicationLagMs\" Cluster=\"${local.name}\" Service=\"shard\"', 'p95', 60))"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "lag_p95"
                label      = "p95"
                expression = "AVG(METRICS(lag_p95_series))"
                region     = var.aws_region
              }
            ],

            [
              {
                id         = "lag_p99_series"
                expression = "REMOVE_EMPTY(SEARCH('{ShardedKV,Cluster,Service,Shard} MetricName=\"ReplicationLagMs\" Cluster=\"${local.name}\" Service=\"shard\"', 'p99', 60))"
                region     = var.aws_region
              }
            ],
            [
              {
                id         = "lag_p99"
                label      = "p99"
                expression = "AVG(METRICS(lag_p99_series))"
                region     = var.aws_region
              }
            ]
          ]
        }
      },

      # -------------------- Shard keyspace distribution (%) --------------------
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 24
        height = 6
        properties = {
          region = var.aws_region
          title  = "Shard keyspace distribution (%)"
          view   = "timeSeries"
          period = 60
          metrics = [
            [
              {
                expression = "SEARCH('{ShardedKV,Cluster,Service,Shard} MetricName=\"ShardKeyspacePercent\" Cluster=\"${local.name}\" Service=\"coordinator\"', 'Average', 60)"
                label      = "Keyspace % (avg)"
                id         = "e1"
                region     = var.aws_region
              }
            ]
          ]
        }
      },

      # -------------------- Replicas + leader present --------------------
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 24
        height = 6
        properties = {
          region = var.aws_region
          title  = "Replicas / Leader per shard"
          view   = "timeSeries"
          period = 60
          metrics = [
            [
              {
                expression = "SEARCH('{ShardedKV,Cluster,Service,Shard} MetricName=\"ActiveReplicas\" Cluster=\"${local.name}\" Service=\"coordinator\"', 'Maximum', 60)"
                label      = "ActiveReplicas (max)"
                id         = "e1"
                region     = var.aws_region
              }
            ],
            [
              {
                expression = "SEARCH('{ShardedKV,Cluster,Service,Shard} MetricName=\"LeaderPresent\" Cluster=\"${local.name}\" Service=\"coordinator\"', 'Minimum', 60)"
                label      = "LeaderPresent (min)"
                id         = "e2"
                region     = var.aws_region
              }
            ]
          ]
        }
      }
    ]
  })
}
