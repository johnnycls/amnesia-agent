import { useCallback, useEffect, useState } from 'react';
import type { ServerEvent, ServerStatus } from '../../shared/types';
import { useI18n } from '../i18n/i18n';
import { uid, type ChatMessage } from '../lib/messages';

export function useChat(serverStatus: ServerStatus, loadWorkspace: () => Promise<void>) {
  const { t } = useI18n();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingText, setStreamingText] = useState('');
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState('');

  const handleEvent = useCallback((event: ServerEvent) => {
    const data = event.data;
    if (event.type === 'delta') { setStreamingText((current) => current + String(data.text ?? '')); return; }
    if (event.type === 'assistant') {
      const toolCalls = Array.isArray(data.tool_calls) ? data.tool_calls : [];
      if (toolCalls.length > 0) {
        setMessages((current) => [...current, { id: uid(), role: 'tool_call', text: t('toolCall'), data }]);
        return;
      }
      const choices = Array.isArray(data.choices) ? data.choices.filter((choice): choice is string => typeof choice === 'string') : [];
      setStreamingText(''); setMessages((current) => [...current, { id: uid(), role: 'assistant', text: typeof data.answer === 'string' ? data.answer : String(data.content ?? ''), choices }]); return;
    }
    // Legacy wire type (pre-unify); keep for older servers.
    if (event.type === 'tool_call') { setMessages((current) => [...current, { id: uid(), role: 'tool_call', text: t('toolCall'), data }]); return; }
    if (event.type === 'tool_result') { setMessages((current) => [...current, { id: uid(), role: 'tool_result', text: String(data.content ?? ''), data }]); return; }
    if (event.type === 'error') { setMessages((current) => [...current, { id: uid(), role: 'error', text: String(data.message ?? 'The turn failed.') }]); setStreamingText(''); setBusy(false); return; }
    if (event.type === 'done') { setBusy(false); setStreamingText(''); void loadWorkspace().catch(() => undefined); }
  }, [loadWorkspace, t]);

  useEffect(() => window.desktop.api.onTurnEvent(handleEvent), [handleEvent]);

  const send = useCallback(async (value = input) => {
    const text = value.trim();
    if (!text || busy || serverStatus !== 'ready') return;
    setMessages((current) => [...current, { id: uid(), role: 'user', text }]); setInput(''); setStreamingText(''); setBusy(true);
    try { await window.desktop.api.startTurn(text); } catch (error) { setMessages((current) => [...current, { id: uid(), role: 'error', text: error instanceof Error ? error.message : String(error) }]); setBusy(false); }
  }, [busy, input, serverStatus]);
  const cancel = useCallback(async () => { await window.desktop.api.cancelTurn(); setBusy(false); setStreamingText(''); }, []);
  return { messages, streamingText, busy, input, setInput, send, cancel };
}
