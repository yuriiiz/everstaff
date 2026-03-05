import React, { useState, useEffect, memo } from 'react';
import { User, Bot, Terminal, ChevronRight, ChevronDown, Check } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import FileCard from './FileCard';

// Extract <think>...</think> blocks from content for models that embed thinking inline.
export function extractThinkingFromContent(thinking, content) {
    if (thinking || !content) return { thinking, content };
    const match = content.match(/^<think>([\s\S]*?)<\/think>\s*/);
    if (match) {
        return { thinking: match[1], content: content.slice(match[0].length) || null };
    }
    return { thinking, content };
}

export const HitlHistoryCard = ({ args, output, hitlRequests, onResolve, sessionId, sessionStatus, toolCallId }) => {
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [userInput, setUserInput] = useState('');

    const parsedArgs = typeof args === 'string' ? JSON.parse(args) : args;
    const { prompt, type, options, context } = parsedArgs || {};

    let optionsArray = [];
    if (Array.isArray(options)) optionsArray = options;
    else if (typeof options === 'string') {
        try { optionsArray = JSON.parse(options); } catch (e) { optionsArray = options.split(',').map(s => s.trim()); }
    }

    let pendingRequest = hitlRequests?.find(r => {
        if ((r.origin_session_id || r.session_id) !== sessionId || (r.status !== 'pending' && r.status !== 'expired')) return false;

        // 1. Match by tool_call_id (most reliable)
        if (toolCallId && r.tool_call_id === toolCallId) return true;

        // 2. Match by hitl_id if explicitly passed in args
        if (parsedArgs?.hitl_id && r.hitl_id === parsedArgs.hitl_id) return true;

        // 3. Match by prompt content (looser match)
        if (prompt && r.request?.prompt) {
            const p1 = String(prompt).trim();
            const p2 = String(r.request.prompt).trim();
            if (p1 === p2) return true;
            if (p1.includes(p2) || p2.includes(p1)) return true;
        }

        return false;
    });

    if (!pendingRequest && sessionStatus === 'waiting_for_human') {
        const pendingForSession = hitlRequests?.filter(req => req.session_id === sessionId && req.status === 'pending') || [];
        if (pendingForSession.length === 1) {
            pendingRequest = pendingForSession[0];
        }
    }

    let resolution = null;
    if (output) {
        try {
            resolution = JSON.parse(output.content);
        } catch (e) {
            if (output.content.includes("Decision:") || output.content.includes("Decision Outcome")) {
                const decisionLine = output.content.split('\n').find(l => l.includes("Decision:"));
                const decision = decisionLine ? decisionLine.split(':')[1].trim() : output.content;
                resolution = { decision };
            } else {
                resolution = { decision: output.content };
            }
        }
    }

    const isPending = !!pendingRequest && pendingRequest.status === 'pending' && !output;
    const isExpired = !!pendingRequest && pendingRequest.status === 'expired' && !output;

    const handleAction = async (decision, comment = "", extraFields = {}) => {
        if (!isPending) return;
        setIsSubmitting(true);
        try {
            let hitlIdToResolve = pendingRequest?.hitl_id || parsedArgs?.hitl_id;

            if (!hitlIdToResolve) {
                try {
                    const res = await fetch('/api/hitl');
                    const freshRequests = await res.json();
                    const match = freshRequests.find(r =>
                        (r.origin_session_id || r.session_id) === sessionId &&
                        r.status === 'pending' &&
                        (toolCallId ? r.tool_call_id === toolCallId : String(r.request?.prompt).trim() === String(prompt).trim())
                    );
                    if (match) hitlIdToResolve = match.hitl_id;
                } catch (e) {
                    console.error("Failed to fetch fresh HITL requests:", e);
                }
            }

            if (!hitlIdToResolve) throw new Error("Could not definitively identify which HITL request to resolve.");

            await onResolve(hitlIdToResolve, decision, comment, { ...extraFields, tool_call_id: toolCallId });
            setUserInput('');
        } catch (e) {
            console.error("Resolution error:", e);
            alert(`Failed to submit decision: ${e.message}`);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="hitl-card">
            <div className="hitl-header">
                {resolution ? (
                    <Check size={14} className="hitl-icon-resolved" />
                ) : isExpired ? (
                    <div className="hitl-icon-expired" title="Request Expired"></div>
                ) : (
                    <div className="hitl-icon-pending">
                        <div className="hitl-spinner" />
                    </div>
                )}
                <span>Human Input Requested</span>
                {resolution && <span className="hitl-badge-resolved">Resolved</span>}
                {isExpired && <span className="hitl-badge-expired">Expired</span>}
                {isPending && <span className="hitl-badge-pending">Pending</span>}
            </div>

            <div className="hitl-body">
                <div className="hitl-prompt">{prompt || 'Agent is waiting for your input...'}</div>

                {context && (
                    <div className="hitl-context">
                        <div className="hitl-context-title">Context:</div>
                        <pre className="hitl-context-content">{typeof context === 'string' ? context : JSON.stringify(context, null, 2)}</pre>
                    </div>
                )}

                {resolution ? (
                    <div className="hitl-resolution">
                        <div className="hitl-resolution-title">Decision Details:</div>
                        <div className="hitl-resolution-content" style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', color: '#047857' }}>
                            {resolution.decision || JSON.stringify(resolution)}
                        </div>
                    </div>
                ) : isPending ? (
                    <div className="hitl-actions">
                        {type === 'options' && optionsArray.length > 0 ? (
                            <div className="hitl-options-container">
                                {optionsArray.map((opt, i) => (
                                    <button
                                        key={i}
                                        className="hitl-btn hitl-btn-primary"
                                        onClick={() => handleAction(opt)}
                                        disabled={isSubmitting}
                                    >
                                        {opt}
                                    </button>
                                ))}
                            </div>
                        ) : (
                            <div className="hitl-input-container">
                                <input
                                    className="hitl-input"
                                    placeholder="Type your response..."
                                    value={userInput}
                                    onChange={e => setUserInput(e.target.value)}
                                    onKeyDown={e => {
                                        if (e.key === 'Enter' && userInput.trim() && !isSubmitting) {
                                            handleAction('provide_input', userInput.trim(), { input: userInput.trim() });
                                        }
                                    }}
                                    disabled={isSubmitting}
                                />
                                <button
                                    className="hitl-btn hitl-btn-primary"
                                    onClick={() => handleAction('provide_input', userInput.trim(), { input: userInput.trim() })}
                                    disabled={!userInput.trim() || isSubmitting}
                                >
                                    {isSubmitting ? 'Submitting...' : 'Submit'}
                                </button>
                            </div>
                        )}
                        {/* Always offer a cancel/reject option */}
                        <button
                            className="hitl-btn hitl-btn-danger"
                            onClick={() => handleAction('reject', 'User rejected the request')}
                            disabled={isSubmitting}
                            style={{ marginTop: '8px' }}
                        >
                            Decline / Cancel
                        </button>
                    </div>
                ) : null}
            </div>
        </div>
    );
};

export const MessageItem = memo(({ message, agentName, hitlRequests, onResolve, sessionId, sessionStatus, onPreviewFile }) => {
    const isUser = message.role === 'user';
    const hasTools = message.tool_calls && message.tool_calls.length > 0;
    const { thinking: displayThinking, content: displayContent } = extractThinkingFromContent(
        message.thinking,
        message.content
    );

    const isContentEmpty = !displayContent || displayContent.trim() === '';
    const [isThinkingExpanded, setIsThinkingExpanded] = useState(isContentEmpty);

    useEffect(() => {
        if (isContentEmpty) {
            setIsThinkingExpanded(true);
        }
    }, [isContentEmpty]);

    return (
        <div className={`message-row ${isUser ? 'message-row-user' : 'message-row-agent'}`}>
            <div className={`message-avatar ${isUser ? 'avatar-user' : 'avatar-agent'}`}>
                {isUser ? <User size={14} /> : <Bot size={16} />}
            </div>

            <div className={`message-content-wrapper ${isUser ? 'wrapper-user' : 'wrapper-agent'}`}>
                <div className="message-sender-name">
                    {isUser ? 'You' : `Agent: ${agentName || 'Agent'}`}
                </div>

                <div className={`message-bubble ${isUser ? 'bubble-user' : 'bubble-agent'}`}>
                    {/* Thinking Section */}
                    {!isUser && displayThinking && (
                        <div className="message-thinking-section" style={{ marginBottom: isContentEmpty ? 0 : 8 }}>
                            <details className="thinking-details" open={isThinkingExpanded} onToggle={(e) => setIsThinkingExpanded(e.currentTarget.open)}>
                                <summary className="thinking-summary">
                                    <Terminal size={12} />
                                    <span>Thought Chain</span>
                                    <ChevronRight size={12} className="thinking-chevron" />
                                </summary>
                                <div className="thinking-content-container">
                                    <div className="thinking-markdown">
                                        <ReactMarkdown
                                            remarkPlugins={[remarkGfm]}
                                            components={{
                                                p: ({ node, ...props }) => <p className="markdown-p" {...props} />,
                                            }}
                                        >
                                            {displayThinking}
                                        </ReactMarkdown>
                                    </div>
                                    {message.streaming && isContentEmpty && (
                                        <div className="thinking-processing">
                                            <div className="thinking-pulsar" />
                                            <span>Processing</span>
                                        </div>
                                    )}
                                </div>
                            </details>
                        </div>
                    )}

                    {/* Content Section */}
                    {displayContent && displayContent.trim() && (
                        <div className={`message-text-content ${!isUser && displayThinking && isThinkingExpanded ? 'mt-1' : ''}`}>
                            <ReactMarkdown
                                remarkPlugins={[remarkGfm]}
                                components={{
                                    table: ({ node, ...props }) => <table className="markdown-table" {...props} />,
                                    th: ({ node, ...props }) => <th className={`markdown-th ${isUser ? 'th-user' : 'th-agent'}`} {...props} />,
                                    td: ({ node, ...props }) => <td className="markdown-td" {...props} />,
                                    p: ({ node, ...props }) => <p className="markdown-p-margin" {...props} />,
                                    ul: ({ node, ...props }) => <ul className="markdown-ul" {...props} />,
                                    ol: ({ node, ...props }) => <ol className="markdown-ol" {...props} />,
                                    li: ({ node, ...props }) => <li className="markdown-li" {...props} />,
                                    pre: ({ node, ...props }) => <pre className={`markdown-pre ${isUser ? 'pre-user' : 'pre-agent'}`} {...props} />,
                                    code: ({ node, inline, ...props }) => <code className={`markdown-code ${inline ? (isUser ? 'code-inline-user' : 'code-inline-agent') : ''}`} {...props} />,
                                    img: ({ node, ...props }) => <img className="markdown-img" {...props} />,
                                }}
                            >
                                {displayContent}
                            </ReactMarkdown>
                        </div>
                    )}
                </div>

                {/* Tool Calls Blocks */}
                {hasTools && (
                    <div className="tool-calls-container">
                        {message.tool_calls.map((tc, i) => {
                            const outputMsg = message.relatedOutputs?.find(o => o.tool_call_id === tc.id)
                                || (message.relatedOutputs?.[i] && !message.relatedOutputs?.[i].tool_call_id ? message.relatedOutputs?.[i] : null);

                            const isHitl = tc.name === 'request_human_input' || tc.function?.name === 'request_human_input';

                            if (isHitl) {
                                return (
                                    <HitlHistoryCard
                                        key={i}
                                        args={tc.function?.arguments || tc.arguments || tc.args}
                                        output={outputMsg}
                                        hitlRequests={hitlRequests}
                                        onResolve={onResolve}
                                        sessionId={sessionId}
                                        sessionStatus={sessionStatus}
                                        toolCallId={tc.id}
                                    />
                                );
                            }

                            const toolName = tc.name || tc.function?.name;
                            const args = tc.arguments || tc.function?.arguments || tc.args;
                            let parsedArgs = {};
                            try {
                                parsedArgs = typeof args === 'string' ? JSON.parse(args) : args;
                            } catch (e) { }

                            const isDelegate = toolName === 'delegate_task_to_subagent';
                            const delegateAgentName = isDelegate ? (parsedArgs?.agent_name || 'Sub-Agent') : '';

                            let argsStr = '';
                            try {
                                argsStr = typeof args === 'string' ? JSON.stringify(JSON.parse(args)) : JSON.stringify(args);
                            } catch (e) {
                                argsStr = String(args);
                            }

                            return (
                                <div key={i} className="tool-call-block">
                                    <details className="tool-call-details">
                                        <summary className="tool-call-summary">
                                            {(outputMsg || tc._streaming === false) ? (
                                                <Check size={14} className={`tool-call-status-icon ${outputMsg ? 'status-success' : 'status-pending'}`} />
                                            ) : (
                                                <div className="tool-loading-container">
                                                    <div className="tool-loading-spinner" />
                                                </div>
                                            )}
                                            <span className="tool-call-title">
                                                {isDelegate ? (
                                                    <span>Delegate Task to <span className="delegate-agent-name">{delegateAgentName}</span></span>
                                                ) : (
                                                    <>Function Call: <span className="tool-name">{toolName}</span>: <span className="tool-args-preview">{argsStr.slice(0, 80)}{argsStr.length > 80 ? '...' : ''}</span></>
                                                )}
                                            </span>
                                            <ChevronRight size={14} className="details-chevron" />
                                        </summary>
                                        <div className="tool-call-body">
                                            <div className="tool-call-section-title">Arguments:</div>
                                            <pre className="tool-call-pre">
                                                {JSON.stringify(parsedArgs, null, 2)}
                                            </pre>
                                            {outputMsg && (
                                                <>
                                                    <div className="tool-call-section-title mt-2">Output:</div>
                                                    <pre className="tool-call-pre tool-call-output">
                                                        {outputMsg.content}
                                                    </pre>
                                                </>
                                            )}
                                        </div>
                                    </details>
                                </div>
                            );
                        })}
                    </div>
                )}
                {message.fileArtifacts && message.fileArtifacts.length > 0 && (
                    <div className="file-artifacts-container">
                        {message.fileArtifacts.map((f, i) => (
                            <FileCard key={i} file={f} sessionId={sessionId} onPreview={onPreviewFile} />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
});
