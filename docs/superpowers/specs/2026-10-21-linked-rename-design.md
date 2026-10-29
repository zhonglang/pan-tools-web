# 关联重命名设计

日期：2026-10-21  
状态：已确认

## 目标

在转存页支持「关联重命名」：主网盘主目录下改一个漫剧文件夹名后，同组其他网盘目录里相同数字前缀的文件夹改成同一名字。

## 配置

系统配置中独立维护一组（不与资源库同步目录混用）：

| 字段 | 说明 |
|------|------|
| primary_account_id | 主账号 |
| primary_directory | 主目录 path |
| peers | 关联项列表：account_id + directory（可含 label） |

表建议：`linked_rename_group`（每用户一行主配置）+ `linked_rename_peers`，或单表 JSON peers。实现取简单可维护方案。

## 行为

1. 普通「重命名」不变。
2. 仅当当前账号与目录匹配主配置时，显示「关联重命名」。
3. 解析源名数字前缀；无前缀则仅改主侧（或拒绝关联，实现时仅改主侧并提示无法关联）。
4. 主侧改名为 `new_name`；各 peer 目录 list 后找同前缀文件夹，改为完全相同的 `new_name`。
5. 找不到：静默跳过；失败：汇总提示。

## API

- `GET/PUT /api/settings/linked-rename`
- `POST /api/files/linked-rename` → `{ renamed, skipped, failed, errors? }`
