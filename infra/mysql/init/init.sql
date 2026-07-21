-- 智效工坊 MySQL 初始化脚本（容器首次启动执行）
-- 应用 schema 由 Alembic 创建；此处仅做安全 / 字符集强化
SET NAMES utf8mb4;

-- 限流用户使用；可按团队隔离扩展
CREATE DATABASE IF NOT EXISTS `zhixiao` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 防止 root 远程登录（按需调整）
-- DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost','127.0.0.1','::1');