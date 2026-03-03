/**
 * Chat API 调用封装
 */
import { API_BASE_WITH_PREFIX } from "./client";

export interface StreamChunk {
  content: string;
  done: boolean;
  task_id?: string | null;
  session_id?: string | null;
  error?: string | null;
}

export interface ImageAttachment {
  name: string;
  data: string; // Base64
  mime_type?: string;
}

/**
 * 发送聊天消息（流式）
 * @param message 用户消息
 * @param sessionId 会话 ID（用于保持对话上下文）
 * @param enableThink 是否启用思考模式
 * @param images 图片附件列表（Base64）
 * @param signal AbortSignal 用于取消请求
 * @returns 返回 reader 和 decoder
 */
export async function sendChatMessage(
  message: string,
  sessionId: string,
  enableThink: boolean = false,
  images: ImageAttachment[] = [],
  signal?: AbortSignal
): Promise<{
  reader: ReadableStreamDefaultReader<Uint8Array>;
  decoder: TextDecoder;
}> {
  const response = await fetch(`${API_BASE_WITH_PREFIX}/chat/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message: message,
      session_id: sessionId,
      enable_think: enableThink,
      stream: true,
      images: images,
    }),
    signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("无法获取响应流");
  }

  const decoder = new TextDecoder();

  return { reader, decoder };
}

/**
 * 解析 SSE 数据行
 * @param line SSE 格式的数据行
 * @returns 解析后的数据或 null
 */
export function parseSSELine(line: string): StreamChunk | null {
  try {
    // 解析 SSE 格式：data: {...}
    if (line.startsWith("data: ")) {
      const jsonStr = line.substring(6); // 去掉 "data: " 前缀
      return JSON.parse(jsonStr) as StreamChunk;
    }
  } catch (e) {
    console.error("解析 JSON 失败:", e, "原始数据:", line);
  }
  return null;
}

// ============ 语音识别相关 ============

export interface TranscribeResponse {
  text: string;
  language: string;
  language_probability: number;
  duration: number;
}

/**
 * 语音转文字
 * @param audioBlob 录音的 Blob 对象
 * @param language 语言代码（默认 zh）
 * @returns 识别的文字
 */
export async function transcribeAudio(
  audioBlob: Blob,
  language: string = "zh"
): Promise<TranscribeResponse> {
  const formData = new FormData();
  formData.append("audio", audioBlob, "recording.webm");
  formData.append("language", language);

  const response = await fetch(`${API_BASE_WITH_PREFIX}/speech/speech`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`语音识别失败: ${response.status} ${errorText}`);
  }

  return await response.json();
}

/**
 * 获取语音模型状态
 */
export async function getSpeechModelStatus() {
  const response = await fetch(`${API_BASE_WITH_PREFIX}/speech/status`);
  if (!response.ok) {
    throw new Error(`获取模型状态失败: ${response.status}`);
  }
  return await response.json();
}

