/**
 * Session Manager - 会话管理工具类
 * 
 * 职责：
 * 1. 管理匿名用户的 Session ID（存储在 localStorage）
 * 2. 为将来的用户登录系统预留扩展接口
 * 3. 支持新建会话（生成新的 Session ID）
 * 
 * 演进路径：
 * - 阶段 1（当前）：匿名 Session，格式 "anon:timestamp-random"
 * - 阶段 2（将来）：支持用户登录，格式 "user:userId:conv:conversationId"
 * - 阶段 3（将来）：支持多会话管理
 */

export class SessionManager {
  private static readonly STORAGE_KEY = 'chat_session_id';
  private static readonly SESSION_PREFIX_ANON = 'anon';
  private static readonly SESSION_PREFIX_USER = 'user';

  /**
   * 获取当前 Session ID
   * 
   * 逻辑：
   * 1. 如果已登录，返回 user-based session（将来实现）
   * 2. 如果未登录，从 localStorage 读取匿名 session
   * 3. 如果不存在，生成新的匿名 session
   * 
   * @returns Session ID 字符串
   */
  static getSessionId(): string {
    // TODO: 将来检查登录状态
    // if (AuthService.isLoggedIn()) {
    //   return this.getUserSessionId();
    // }

    return this.getAnonymousSessionId();
  }

  /**
   * 获取匿名用户的 Session ID
   * 
   * @returns 匿名 Session ID，格式：anon:timestamp-random
   */
  private static getAnonymousSessionId(): string {
    if (typeof window === 'undefined') {
      // SSR 环境，返回临时 ID
      return this.generateAnonymousSessionId();
    }

    const stored = localStorage.getItem(this.STORAGE_KEY);
    
    // 验证存储的 Session ID 是否有效
    if (stored && this.isValidSessionId(stored)) {
      return stored;
    }

    // 生成新的 Session ID
    const newId = this.generateAnonymousSessionId();
    localStorage.setItem(this.STORAGE_KEY, newId);
    return newId;
  }

  /**
   * 生成新的匿名 Session ID
   * 
   * 格式：anon:timestamp-randomString
   * 示例：anon:1733234567890-a1b2c3d
   * 
   * @returns 新的匿名 Session ID
   */
  private static generateAnonymousSessionId(): string {
    const timestamp = Date.now();
    const random = Math.random().toString(36).substring(2, 9);
    return `${this.SESSION_PREFIX_ANON}:${timestamp}-${random}`;
  }

  /**
   * 验证 Session ID 格式是否有效
   * 
   * @param sessionId Session ID 字符串
   * @returns 是否有效
   */
  private static isValidSessionId(sessionId: string): boolean {
    if (!sessionId || typeof sessionId !== 'string') {
      return false;
    }

    // 匿名 Session 格式：anon:timestamp-random
    if (sessionId.startsWith(`${this.SESSION_PREFIX_ANON}:`)) {
      return true;
    }

    // 用户 Session 格式：user:userId:conv:conversationId（将来支持）
    if (sessionId.startsWith(`${this.SESSION_PREFIX_USER}:`)) {
      return true;
    }

    return false;
  }

  /**
   * 重置 Session（新建会话时调用）
   * 
   * 逻辑：
   * 1. 如果已登录，生成新的 conversation ID（将来实现）
   * 2. 如果未登录，生成新的匿名 session
   * 
   * @returns 新的 Session ID
   */
  static resetSession(): string {
    // TODO: 将来检查登录状态
    // if (AuthService.isLoggedIn()) {
    //   return this.createUserConversation();
    // }

    const newId = this.generateAnonymousSessionId();
    
    if (typeof window !== 'undefined') {
      localStorage.setItem(this.STORAGE_KEY, newId);
    }
    
    return newId;
  }

  /**
   * 清除当前 Session（用户登出时调用）
   */
  static clearSession(): void {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(this.STORAGE_KEY);
    }
  }

  /**
   * 判断当前是否为匿名会话
   * 
   * @returns 是否为匿名会话
   */
  static isAnonymousSession(): boolean {
    const sessionId = this.getSessionId();
    return sessionId.startsWith(`${this.SESSION_PREFIX_ANON}:`);
  }

  // ========== 以下为将来扩展的接口（用户登录功能） ==========

  /**
   * 绑定用户（登录后调用）
   * 
   * 逻辑：
   * 1. 生成 user-based session ID
   * 2. 可选：将匿名 session 的历史迁移到用户账号
   * 
   * @param userId 用户 ID
   * @param conversationId 可选的会话 ID（如果要继续之前的会话）
   * @returns 新的 Session ID
   */
  static bindUser(userId: string, conversationId?: string): string {
    const convId = conversationId || `conv_${Date.now()}`;
    const sessionId = `${this.SESSION_PREFIX_USER}:${userId}:conv:${convId}`;
    
    if (typeof window !== 'undefined') {
      localStorage.setItem(this.STORAGE_KEY, sessionId);
    }
    
    return sessionId;
  }

  /**
   * 获取用户的 Session ID（登录用户专用）
   * 
   * @returns 用户 Session ID
   */
  private static getUserSessionId(): string {
    // TODO: 实现用户 Session 逻辑
    // 1. 从 AuthService 获取 userId
    // 2. 从 localStorage 或 API 获取 active conversation ID
    // 3. 返回 "user:userId:conv:conversationId"
    
    throw new Error('User session not implemented yet');
  }

  /**
   * 创建新的用户会话（登录用户专用）
   * 
   * @returns 新的用户 Session ID
   */
  private static createUserConversation(): string {
    // TODO: 实现创建用户会话逻辑
    // 1. 调用后端 API 创建新会话
    // 2. 返回新的 Session ID
    
    throw new Error('User conversation creation not implemented yet');
  }

  /**
   * 迁移匿名会话到用户账号（登录时可选调用）
   * 
   * @param anonymousSessionId 匿名 Session ID
   * @param userId 用户 ID
   * @returns 是否迁移成功
   */
  static async migrateAnonymousSessionToUser(
    anonymousSessionId: string,
    userId: string
  ): Promise<boolean> {
    // TODO: 实现会话迁移逻辑
    // 1. 调用后端 API，将匿名会话的历史消息迁移到用户账号
    // 2. 返回迁移结果
    
    console.warn('Session migration not implemented yet');
    return false;
  }

  // ========== 调试和工具方法 ==========

  /**
   * 获取 Session 信息（用于调试）
   * 
   * @returns Session 信息对象
   */
  static getSessionInfo(): {
    sessionId: string;
    isAnonymous: boolean;
    userId?: string;
    conversationId?: string;
  } {
    const sessionId = this.getSessionId();
    const isAnonymous = this.isAnonymousSession();

    if (isAnonymous) {
      return {
        sessionId,
        isAnonymous: true,
      };
    }

    // 解析 user session: "user:userId:conv:conversationId"
    const parts = sessionId.split(':');
    if (parts.length >= 4 && parts[0] === this.SESSION_PREFIX_USER) {
      return {
        sessionId,
        isAnonymous: false,
        userId: parts[1],
        conversationId: parts[3],
      };
    }

    return {
      sessionId,
      isAnonymous: false,
    };
  }

  /**
   * 打印 Session 信息到控制台（用于调试）
   */
  static debugSession(): void {
    const info = this.getSessionInfo();
    console.log('[SessionManager] Session Info:', info);
  }
}

