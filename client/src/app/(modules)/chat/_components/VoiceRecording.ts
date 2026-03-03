/**
 * 语音录音 Hook
 */
import { useState, useRef, useCallback } from "react";
import { transcribeAudio } from "@/lib/api/chat";

export function VoiceRecording() {
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0); // 音量级别 0-100
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioLevelIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastChunkSizeRef = useRef<number>(0);

  /**
   * 开始录音
   */
  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      // 创建 MediaRecorder
      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: "audio/webm;codecs=opus",
      });

      audioChunksRef.current = [];
      lastChunkSizeRef.current = 0;

      // 收集音频数据（每100ms收集一次）
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
          lastChunkSizeRef.current = event.data.size;
          
          // 根据数据块大小估算音量（简单但有效）
          // 典型值：静音 < 1000, 正常说话 2000-8000, 大声 > 10000
          const estimatedLevel = Math.min(100, (event.data.size / 8000) * 100);
          setAudioLevel(estimatedLevel);
        }
      };

      // 开始录音，每100ms触发一次 ondataavailable
      mediaRecorder.start(100);
      mediaRecorderRef.current = mediaRecorder;
      setIsRecording(true);

      // 备用：如果 ondataavailable 不频繁触发，用定时器模拟音量波动
      audioLevelIntervalRef.current = setInterval(() => {
        if (lastChunkSizeRef.current > 0) {
          // 根据最近的数据块大小更新音量
          const level = Math.min(100, (lastChunkSizeRef.current / 8000) * 100);
          setAudioLevel(level + Math.random() * 10 - 5); // 添加轻微随机波动
        } else {
          // 如果没有数据，显示基础活动
          setAudioLevel(20 + Math.random() * 15);
        }
      }, 150);

      console.log("✅ 开始录音");
    } catch (error) {
      console.error("录音失败:", error);
      alert("无法访问麦克风，请检查权限设置");
    }
  }, []);

  /**
   * 停止录音并识别
   */
  const stopRecording = useCallback(async (): Promise<string | null> => {
    return new Promise((resolve) => {
      const mediaRecorder = mediaRecorderRef.current;
      if (!mediaRecorder || mediaRecorder.state === "inactive") {
        resolve(null);
        return;
      }

      mediaRecorder.onstop = async () => {
        console.log("⏹️ 录音停止");
        setIsRecording(false);
        setIsTranscribing(true);
        setAudioLevel(0);

        // 清除定时器
        if (audioLevelIntervalRef.current) {
          clearInterval(audioLevelIntervalRef.current);
          audioLevelIntervalRef.current = null;
        }

        // 停止所有音频轨道
        const stream = mediaRecorder.stream;
        stream.getTracks().forEach((track) => track.stop());

        try {
          // 合并音频数据
          const audioBlob = new Blob(audioChunksRef.current, {
            type: "audio/webm",
          });

          console.log("🎤 音频大小:", (audioBlob.size / 1024).toFixed(2), "KB");

          if (audioBlob.size < 1000) {
            // 音频太小，可能是空的
            alert("录音时间过短，请重试");
            setIsTranscribing(false);
            resolve(null);
            return;
          }

          // 调用识别 API
          console.log("🔄 开始识别...");
          const result = await transcribeAudio(audioBlob);
          console.log("✅ 识别成功:", result.text);

          setIsTranscribing(false);
          resolve(result.text);
        } catch (error) {
          console.error("识别失败:", error);
          setIsTranscribing(false);
          alert(`语音识别失败: ${error instanceof Error ? error.message : "未知错误"}`);
          resolve(null);
        }
      };

      mediaRecorder.stop();
    });
  }, []);

  /**
   * 切换录音状态
   */
  const toggleRecording = useCallback(async (): Promise<string | null> => {
    if (isRecording) {
      return await stopRecording();
    } else {
      await startRecording();
      return null;
    }
  }, [isRecording, startRecording, stopRecording]);

  return {
    isRecording,
    isTranscribing,
    audioLevel,
    toggleRecording,
    startRecording,
    stopRecording,
  };
}

