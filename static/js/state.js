/* =========================================================
   state.js — 前端共享状态与本地存储
   只负责「现在是什么状态」：不碰 DOM，也不发请求。
   其他模块读写这里的数据，避免变量散落在各个文件里。
   ========================================================= */

export const TOKEN_KEY = "ai_chat_token";
export const USER_KEY = "ai_chat_username";
export const API_KEY_STORE = "ai_chat_api_key";

/**
 * 全局状态对象。
 * token / username / apiKey 来自 localStorage（刷新后仍在），
 * 其余字段只在当前页面生命周期内有效。
 */
export const state = {
    token: localStorage.getItem(TOKEN_KEY) || null,
    username: localStorage.getItem(USER_KEY) || "",
    apiKey: localStorage.getItem(API_KEY_STORE) || "",
    authMode: "login",        // 登录表单当前模式：login | register
    historyBefore: null,      // 历史分页游标：下一页从哪个 message id 往前取
    hasMoreHistory: false,    // 服务端是否还有更早的消息
    loadingHistory: false,    // 防止上翻时重复触发同一页请求
    pinnedToBottom: true,     // 用户是否停在最底部，决定新内容是否自动跟随滚动
};

/** 登录成功后写入 token 与用户名，供下次打开页面免登录。 */
export function saveAuth(token, username) {
    state.token = token;
    state.username = username;
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, username);
}

/** 退出登录：清掉登录态，但保留用户自己配置的 API Key。 */
export function clearAuth() {
    state.token = null;
    state.username = "";
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
}

/** 保存用户手动填写的 API Key。 */
export function saveApiKey(key) {
    state.apiKey = key;
    localStorage.setItem(API_KEY_STORE, key);
}
