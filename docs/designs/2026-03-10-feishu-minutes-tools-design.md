# Feishu Minutes (妙记) Tools Design

## Overview

为 everstaff 的飞书工具集新增 `minutes` 分类，支持获取妙记元信息、转写内容和观看统计。

## API Endpoints

| 工具名 | API | 方法 | 说明 |
|--------|-----|------|------|
| `feishu_get_minute` | `/minutes/v1/minutes/{minute_token}` | GET | 获取元信息（标题、时长、创建者、链接） |
| `feishu_get_minute_transcript` | `/minutes/v1/minutes/{minute_token}/transcripts` | GET | 获取转写内容 |
| `feishu_get_minute_statistics` | `/minutes/v1/minutes/{minute_token}/statistics` | GET | 获取观看统计 |

OAuth scope: `minutes:minutes`

## Tool Details

### feishu_get_minute

参数:
- `minute_token` (str, required): 妙记唯一标识，通常是妙记链接末尾 24 位字符串
- `user_id_type` (str, optional): 用户 ID 类型，默认 `open_id`

返回: 妙记元信息 JSON（token, owner_id, create_time, title, cover, duration, url）

### feishu_get_minute_transcript

参数:
- `minute_token` (str, required): 妙记唯一标识
- `raw` (bool, optional): 默认 False，返回格式化文本；True 返回原始 JSON

格式化输出示例:
```
[张三 00:01:30] 今天讨论一下项目进度...
[李四 00:02:15] 我这边的部分已经完成了...
```

### feishu_get_minute_statistics

参数:
- `minute_token` (str, required): 妙记唯一标识

返回: 观看统计 JSON

## Architecture

- 新建 `src/everstaff/tools/feishu/tools/minutes_tools.py`
- 使用直接 OAPI 调用（httpx），与 calendar/tasks 工具一致
- 工厂函数 `make_feishu_minutes_tools()` 签名与其他工具类一致
- 通过 `call_with_auth_retry` 处理 OAuth 认证

## Integration Points

1. **registry.py**: `_TOOL_CATALOG` 新增 `"minutes"` 分类；`create_feishu_tools()` 新增分支；默认分类列表加 `"minutes"`
2. **config.py**: `LarkWsChannelConfig` 注释更新有效值
3. **docs/usage.md**: 示例配置加 `"minutes"`
4. **scaffold.py**: scaffold 模板更新
5. **GET /tools/lark API**: 自动生效，无需代码改动
6. **测试**: 新增 `test_minutes_tools.py`，更新已有 catalog/registry 测试
