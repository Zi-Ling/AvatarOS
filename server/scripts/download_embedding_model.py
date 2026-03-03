"""
下载 BGE-M3 嵌入模型（ONNX 版本）到本地

模型：BAAI/bge-m3
- 支持 100+ 语言（中英日韩等）
- 向量维度：1024
- ONNX 模型大小：约 1.1GB

目标路径：server/app/models/embeddings/multilingual/bge-m3/
  ├── onnx/
  │   └── model.onnx
  ├── tokenizer_config.json
  ├── tokenizer.json
  └── sentencepiece.bpe.model
"""
import sys
from pathlib import Path

# 目标目录（与 config.py 中 embedding_model_path 一致）
BASE_DIR = Path(__file__).parent.parent / "app" / "models" / "embeddings" / "multilingual" / "bge-m3"
ONNX_DIR = BASE_DIR / "onnx"

HF_REPO = "BAAI/bge-m3"

# ONNX 目录需要的文件
ONNX_FILES = [
    "onnx/model.onnx",
]

# tokenizer 文件（放在 bge-m3/ 根目录）
TOKENIZER_FILES = [
    "tokenizer_config.json",
    "tokenizer.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
]


def download():
    print("=" * 60)
    print("📥 下载 BGE-M3 嵌入模型 (ONNX)")
    print("=" * 60)
    print(f"\n模型: {HF_REPO}")
    print(f"目标路径: {BASE_DIR.absolute()}")
    print("\n注意：模型约 1.1GB，首次下载需要一些时间\n")

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("❌ 缺少依赖: huggingface_hub")
        print("请先安装: pip install huggingface-hub")
        sys.exit(1)

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    ONNX_DIR.mkdir(parents=True, exist_ok=True)

    # 下载 ONNX 模型文件
    print("📦 下载 ONNX 模型文件...")
    for f in ONNX_FILES:
        dest = BASE_DIR / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            print(f"   ✅ 已存在，跳过: {f}")
            continue
        print(f"   ⬇️  {f} ...")
        try:
            hf_hub_download(
                repo_id=HF_REPO,
                filename=f,
                local_dir=str(BASE_DIR),
            )
            print(f"   ✅ {f}")
        except Exception as e:
            print(f"   ❌ 下载失败: {f} — {e}")
            print("\n提示：如果网络受限，可以手动从以下地址下载：")
            print(f"   https://huggingface.co/{HF_REPO}/resolve/main/{f}")
            print(f"   保存到: {dest.absolute()}")
            sys.exit(1)

    # 下载 tokenizer 文件
    print("\n📦 下载 Tokenizer 文件...")
    for f in TOKENIZER_FILES:
        dest = BASE_DIR / f
        if dest.exists():
            print(f"   ✅ 已存在，跳过: {f}")
            continue
        print(f"   ⬇️  {f} ...")
        try:
            hf_hub_download(
                repo_id=HF_REPO,
                filename=f,
                local_dir=str(BASE_DIR),
            )
            print(f"   ✅ {f}")
        except Exception as e:
            print(f"   ⚠️  {f} 下载失败（非必须）: {e}")

    print("\n" + "=" * 60)
    print("✅ 下载完成！")
    print("=" * 60)
    print(f"\n模型路径: {ONNX_DIR.absolute()}")
    print("\n验证文件:")
    for f in ["onnx/model.onnx", "tokenizer_config.json", "tokenizer.json"]:
        p = BASE_DIR / f
        status = "✅" if p.exists() else "❌ 缺失"
        size = f"({p.stat().st_size / 1024 / 1024:.1f} MB)" if p.exists() else ""
        print(f"   {status} {f} {size}")

    print("\n现在可以启动服务了：")
    print("   python main.py")


if __name__ == "__main__":
    # 国内网络提示
    print("💡 提示：如果在国内网络下载较慢，可以设置镜像：")
    print("   $env:HF_ENDPOINT='https://hf-mirror.com'  (PowerShell)")
    print("   export HF_ENDPOINT=https://hf-mirror.com  (Linux/Mac)")
    print()
    download()
