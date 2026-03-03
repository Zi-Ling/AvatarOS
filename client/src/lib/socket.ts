import { io, Socket } from "socket.io-client";

// Prevent multiple instances during hot-reloading in development
let socket: Socket | undefined;

export const getSocket = (): Socket => {
  if (!socket) {
    // Use the Next.js proxy or direct backend URL
    // In dev, we usually point to localhost:8000 if not proxying
    // Assuming the backend is at http://localhost:8000 based on server config
    const URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    
    socket = io(URL, {
      autoConnect: false, // We will connect manually in the Provider
      reconnection: true, // 使用 Socket.IO 内置重连（指数退避）
      reconnectionAttempts: 10,
      reconnectionDelay: 1000, // 初始 1s
      reconnectionDelayMax: 30000, // 最大 30s
      transports: ["websocket", "polling"],
    });
    
    console.log("🔌 Socket instance created pointing to:", URL);
  }
  return socket;
};

