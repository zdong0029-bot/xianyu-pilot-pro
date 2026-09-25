-- Keyword watches and observed item metrics. Unknown counters remain NULL.
CREATE TABLE IF NOT EXISTS `market_watch` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `tenant_id` BIGINT NOT NULL,
  `user_id` BIGINT NOT NULL,
  `account_id` BIGINT NOT NULL,
  `keyword` VARCHAR(80) NOT NULL,
  `search_mode` VARCHAR(8) NOT NULL DEFAULT 'auto',
  `interval_minutes` INT NOT NULL DEFAULT 120,
  `enabled` TINYINT NOT NULL DEFAULT 1,
  `next_run_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `last_run_at` DATETIME NULL,
  `lock_until` DATETIME NULL,
  `last_error` VARCHAR(500) NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_market_watch_due` (`enabled`, `next_run_at`),
  KEY `idx_market_watch_tenant` (`tenant_id`, `user_id`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `market_snapshot` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `tenant_id` BIGINT NOT NULL,
  `watch_id` BIGINT NOT NULL,
  `account_id` BIGINT NOT NULL,
  `item_id` VARCHAR(80) NOT NULL,
  `title` VARCHAR(300) NOT NULL DEFAULT '',
  `price` DECIMAL(12,2) NULL,
  `link` VARCHAR(500) NOT NULL DEFAULT '',
  `image` VARCHAR(500) NOT NULL DEFAULT '',
  `view_count` BIGINT NULL,
  `want_count` BIGINT NULL,
  `sold_count` BIGINT NULL,
  `captured_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_market_snapshot_watch_time` (`tenant_id`, `watch_id`, `captured_at`, `id`),
  KEY `idx_market_snapshot_item_time` (`tenant_id`, `item_id`, `captured_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `market_price_quote` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `tenant_id` BIGINT NOT NULL,
  `item_id` VARCHAR(80) NOT NULL,
  `platform` VARCHAR(16) NOT NULL,
  `source_url` VARCHAR(500) NOT NULL,
  `model_evidence` VARCHAR(300) NOT NULL,
  `price` DECIMAL(12,2) NOT NULL,
  `shipping` DECIMAL(12,2) NOT NULL DEFAULT 0,
  `minimum_quantity` INT NOT NULL DEFAULT 1,
  `source_type` VARCHAR(16) NOT NULL DEFAULT 'manual',
  `observed_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_market_quote_item` (`tenant_id`, `item_id`, `observed_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
