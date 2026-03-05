import { useState, useRef, useEffect, memo } from 'react';
import { Bot, Sparkles, Terminal, Cpu, Zap, X, Send, Square } from 'lucide-react';

export const CREATOR_SUGGESTIONS = {
    'builtin_agent_creator': [
        { icon: Bot, text: "Build a tech trend monitoring agent using Reddit and AI summaries." },
        { icon: Sparkles, text: "Design a bedtime story architect for personalized children's tales." },
        { icon: Terminal, text: "Create a rigorous code auditor focusing on security and performance." }
    ],
    'builtin_skill_creator': [
        { icon: Cpu, text: "Build a skill that transcribes audio and translates it instantly." },
        { icon: Zap, text: "Create a financial data fetcher that generates weekly LaTeX reports." },
        { icon: Terminal, text: "Implement a GitHub issue monitor with intelligent label matching." }
    ]
};

const SuggestedAction = memo(({ icon: Icon, text, onClick }) => (
    <div
        className="suggested-action-card"
        onClick={() => onClick(text)}
    >
        <div className="suggested-action-icon">
            <Icon size={18} />
        </div>
        <div className="suggested-action-text">{text}</div>
    </div>
));

export const ChatInput = memo(({
    selectedSession,
    isAgentOnline,
    isWaitingForInput,
    isProcessing,
    isConnected,
    isConnecting,
    currentHitlPayload,
    onSendMessage,
    onStop,
    onRetry,
    statusContent,
    renderMessagesCount
}) => {
    const [input, setInput] = useState('');
    const inputRef = useRef(null);

    const handleSend = () => {
        if (!input.trim()) return;
        onSendMessage(input);
        setInput('');
    };

    // Auto-focus input field whenever session changes or becomes ready
    useEffect(() => {
        if (selectedSession && inputRef.current && !inputRef.current.disabled) {
            inputRef.current.focus();
        }
    }, [selectedSession?.session_id, isConnected, selectedSession?.isNew, isAgentOnline, isWaitingForInput]);

    return (
        <div className="chat-input-container">
            {/* Error Message & Retry for Failed Sessions */}
            {selectedSession?.status === 'failed' && !isProcessing && (
                <div className="chat-error-banner fade-in">
                    <div className="chat-error-content">
                        <div className="chat-error-icon">
                            <X size={14} strokeWidth={3} />
                        </div>
                        <div className="chat-error-text-container">
                            <div className="chat-error-title">Session Error</div>
                            {selectedSession.error && (
                                <div className="chat-error-desc" title={selectedSession.error}>
                                    {selectedSession.error}
                                </div>
                            )}
                        </div>
                    </div>
                    <button className="chat-error-retry-btn" onClick={onRetry}>
                        <Zap size={12} fill="currentColor" />
                        RETRY
                    </button>
                </div>
            )}

            {/* Suggested Actions for Creator Agents */}
            {selectedSession?.isNew && selectedSession.agent_uuid && CREATOR_SUGGESTIONS[selectedSession.agent_uuid] && renderMessagesCount === 1 && (
                <div className="suggested-actions-container fade-in">
                    {CREATOR_SUGGESTIONS[selectedSession.agent_uuid].map((s, i) => (
                        <SuggestedAction
                            key={i}
                            icon={s.icon}
                            text={s.text}
                            onClick={(val) => setInput(val)}
                        />
                    ))}
                </div>
            )}

            <div className={`chat-input-wrapper ${(!isAgentOnline && selectedSession) ? 'opacity-70' : ''}`}>
                <input
                    ref={inputRef}
                    className={`chat-input-field ${(isWaitingForInput) ? 'waiting' : ''}`}
                    style={{
                        cursor: (!isAgentOnline && !isWaitingForInput) ? 'not-allowed' : 'text'
                    }}
                    placeholder={
                        isWaitingForInput
                            ? `REPLY TO: ${currentHitlPayload?.prompt || 'Input required...'}`
                            : selectedSession && !isAgentOnline
                                ? `Agent "${selectedSession.agent_name}" is offline/deleted.`
                                : (selectedSession?.isNew ? "Type your first message to start..." : (isConnected ? "Type a message..." : (isConnecting ? "Connecting..." : "Disconnected. Refresh or reselect a session.")))
                    }
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => {
                        if (e.key === 'Enter' && !e.nativeEvent.isComposing && (isAgentOnline || isWaitingForInput)) {
                            e.preventDefault();
                            handleSend();
                        }
                    }}
                    disabled={isWaitingForInput ? false : ((!isConnected && !selectedSession?.isNew) || !isAgentOnline)}
                    autoFocus
                />

                <button
                    className={`chat-send-btn ${isWaitingForInput ? (input.trim() ? 'active' : 'disabled') : ((isConnected || selectedSession?.isNew) && input.trim() && isAgentOnline ? 'active' : 'disabled')}`}
                    onClick={handleSend}
                    disabled={isWaitingForInput ? !input.trim() : ((!isConnected && !selectedSession?.isNew) || !input.trim() || !isAgentOnline)}
                >
                    <Send size={14} />
                </button>

                {isProcessing && (
                    <button
                        className="chat-stop-btn"
                        onClick={onStop}
                        title="Stop Session"
                    >
                        <Square size={12} fill="#ef4444" />
                    </button>
                )}
            </div>

            {(() => {
                const displayStatus = isProcessing ? (statusContent || 'Thinking...') : (selectedSession?.isNew ? '' : selectedSession?.status);
                if (!displayStatus) return null;

                const statusStyles = {
                    'running': { color: '#3b82f6', label: 'Processing...', dot: '#3b82f6', pulse: true },
                    'cancelled': { color: '#6b7280', label: 'Stopped', dot: '#9ca3af', pulse: false },
                    'completed': { color: '#10b981', label: 'Completed', dot: '#10b981', pulse: false },
                    'failed': { color: '#ef4444', label: 'Error', dot: '#ef4444', pulse: false },
                    'interrupted': { color: '#f59e0b', label: 'Interrupted', dot: '#f59e0b', pulse: false },
                    'waiting_for_human': { color: '#8b5cf6', label: 'Waiting for approval', dot: '#8b5cf6', pulse: true }
                };

                const style = statusStyles[isProcessing ? 'running' : displayStatus] || { color: '#6b7280', label: displayStatus, dot: '#9ca3af', pulse: false };

                return (
                    <div className="chat-status-indicator" style={{ color: style.color }}>
                        <div className="status-dot" style={{
                            background: style.dot,
                            animation: style.pulse ? 'pulse 1.5s infinite' : 'none',
                            opacity: style.pulse ? 1 : 0.6
                        }} />
                        <span>{isProcessing ? (statusContent || style.label) : style.label}</span>
                    </div>
                );
            })()}
        </div>
    );
});
