"""
下载多语言嵌入模型到本地

模型：paraphrase-multilingual-MiniLM-L12-v2
- 支持 50+ 语言（中英日韩等）
- 向量维度：384
- 模型大小：约 118MB
"""
import sys
from pathlib import Path

# 模型配置
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
LOCAL_PATH = Path(__file__).parent / "models" / "embeddings" / "multilingual"


def download_model():
    """下载模型到本地目录"""
    print("=" * 60)
    print("📥 下载多语言嵌入模型")
    print("=" * 60)
    print(f"\n模型: {MODEL_NAME}")
    print(f"目标路径: {LOCAL_PATH.absolute()}")
    
    # 确保目录存在
    LOCAL_PATH.mkdir(parents=True, exist_ok=True)
    
    try:
        from sentence_transformers import SentenceTransformer
        
        print("\n开始下载...")
        print("（首次下载可能需要几分钟，取决于网络速度）")
        
        # 下载并加载模型
        model = SentenceTransformer(MODEL_NAME)
        
        print("\n保存到本地...")
        # 保存到指定目录
        model.save(str(LOCAL_PATH))
        
        print("\n" + "=" * 60)
        print("✅ 下载完成！")
        print("=" * 60)
        print(f"\n模型已保存到: {LOCAL_PATH.absolute()}")
        print(f"向量维度: {model.get_sentence_embedding_dimension()}")
        
        # 测试模型
        print("\n🧪 测试模型...")
        test_texts = [
            "你好世界",
            "Hello world",
            "こんにちは世界",
        ]
        
        embeddings = model.encode(test_texts)
        print(f"   测试文本数: {len(test_texts)}")
        print(f"   生成向量: {embeddings.shape}")
        
        # 测试相似度
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np
        
        sim_matrix = cosine_similarity(embeddings)
        print("\n   相似度矩阵:")
        for i, text in enumerate(test_texts):
            print(f"   {text}:")
            for j, text2 in enumerate(test_texts):
                if i != j:
                    print(f"      vs {text2}: {sim_matrix[i][j]:.3f}")
        
        print("\n🎉 模型可用！")
        
        # 显示配置说明
        print("\n" + "=" * 60)
        print("📝 配置说明")
        print("=" * 60)
        print("\n在 config.yaml 中添加：")
        print("""
embedding:
  model_path: "../app/models/embeddings/multilingual"
  model_name: "paraphrase-multilingual-MiniLM-L12-v2"
""")
        
        print("\n或在代码中使用：")
        print(f"""
from app.avatar.infra.semantic import get_embedding_service

service = get_embedding_service()
service.initialize(model_name="{LOCAL_PATH.absolute()}")
""")
        
    except ImportError:
        print("\n❌ 缺少依赖包")
        print("\n请安装: pip install sentence-transformers")
        sys.exit(1)
    
    except Exception as e:
        print(f"\n❌ 下载失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    download_model()

