# WASM 插件目录

这个目录存放预编译的 WASM 插件（.wasm 文件）。

## 插件命名规则

插件文件名必须与 Skill 的 `api_name` 对应：
- `api_name`: `regex.extract` → 文件名: `regex_extract.wasm`
- `api_name`: `json.parse` → 文件名: `json_parse.wasm`
- `api_name`: `base64.encode` → 文件名: `base64_encode.wasm`

## 插件开发

参考 `docs/WASM_PLUGIN_GUIDE.md` 了解如何开发 WASM 插件。

## 当前插件

目前没有任何插件。Phase 2.2 将实现第一个插件（regex_extract）。

## 安全说明

所有插件都在 WASM 沙箱中执行，禁用了所有 WASI 能力：
- ❌ 无文件系统访问
- ❌ 无网络访问
- ❌ 无环境变量
- ❌ 无子进程
- ✅ 仅纯计算和内存操作
