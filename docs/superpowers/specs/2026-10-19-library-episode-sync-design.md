# 资源库集数同步设计

日期：2026-10-19  
状态：已确认

## 目标

在资源库页提供「同步」：按系统配置中的多个账号+目录，扫描文件夹名，只更新 `library_items.finished` / `latest_episode`。

## 配置

表 `library_sync_sources`（按用户）：

| 字段 | 说明 |
|------|------|
| id | 主键 |
| user_id | 用户 |
| account_id | 网盘账号 |
| directory | 目录 path |
| label | 可选备注 |
| sort_order | 扫描顺序 |
| created_at / updated_at | 时间 |

系统配置页维护列表；支持多条。

## 同步

1. 读取当前用户全部 sync sources（按 sort_order）
2. 对各源 `list_dir`，只取文件夹
3. 解析 `序号 名称#完结#集数`（仍兼容旧的 `｜`）
4. 按 prefix 匹配已有 `library_items`，仅更新完结/集数
5. 同 prefix 多目录：后扫覆盖先前
6. 不改名、不新建、不删除

## API

- `GET/PUT /api/settings/library-sync-sources`
- `POST /api/library/sync-episodes` → `{ updated, unchanged, unmatched, items }`
