# DWG 图纸读取 Skill

用于 Codex 读取 DWG 中的文字、图层、块属性、坐标及边界，并按确认的区块归类工程标高。

## 安装与使用

将本仓库克隆至 Codex 的个人技能目录：

```bash
git clone https://github.com/tiger1974333/dwg-reader.git ~/.codex/skills/dwg-reader
```

如果该目录已经存在，请先检查现有版本，避免覆盖本地修改。

在 Codex 中提交 DWG 文件并使用：

> 请使用 $dwg-reader 读取这份 DWG，汇总各区块的回填前标高、回填后标高和高差，生成 Excel，逐点明细按一个区块一个工作表。

## 运行依赖

- Python 3。
- GNU LibreDWG 的 `dwgread`，安装或构建方法见 [toolchain.md](references/toolchain.md)。仓库不包含平台专用二进制。
- 区块标高归类脚本需要 Shapely（支持 `make_valid` 的版本）。Excel 生成由可用的表格技能完成。

读取脚本会查找 `DWGREAD_BIN`、PATH 及 Codex 用户工具缓存，也支持显式传入 `--dwgread`。

## 数据核对

标高通过所属块及属性句柄配对，属性含义须根据图纸证据确认。设计标高不能自动视为竣工实测标高。高差按回填后减回填前计算，共同边界点、区块外点、重复点和冲突值分别记录。自定义或代理对象可能无法完整读取。

## 验证

```bash
python3 scripts/verify_workflow.py
```

验证包含属性归属、重复与冲突、共同边界、区块外点、负高差、异常几何及截断 JSON 等案例；需要 Shapely。

详细流程见 [SKILL.md](SKILL.md)。本仓库仅包含通用技能与合成验证案例，不包含实际项目图纸或测点数据。
