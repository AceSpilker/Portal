/** AI 流式对话 WS 地址（P13）：跟随页面协议与 host，token 走 query（豁免面同 /ws/*）。 */

export function buildAiWsUrl(token: string): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws/ai-chat?token=${encodeURIComponent(token)}`;
}
