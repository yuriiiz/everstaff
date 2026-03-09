import React, { useState, useEffect, memo } from 'react';
import { User, Bot, Terminal, ChevronRight, ChevronDown, Check, Folder } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import FileCard from './FileCard';
import { Excalidraw } from '@excalidraw/excalidraw';
import { MermaidPreview } from './FilePreviewModal';
import "@excalidraw/excalidraw/index.css";

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
    const [submittingAction, setSubmittingAction] = useState(null);
    const [userInput, setUserInput] = useState('');
    const [localResolution, setLocalResolution] = useState(null);

    const parsedArgs = typeof args === 'string' ? JSON.parse(args) : args;
    const { prompt, type, options, context, tool_permission_options } = parsedArgs || {};

    let optionsArray = [];
    if (Array.isArray(options)) optionsArray = options;
    else if (typeof options === 'string') {
        try { optionsArray = JSON.parse(options); } catch (e) { optionsArray = options.split(',').map(s => s.trim()); }
    }

    let pendingRequest = hitlRequests?.find(r => {
        if ((r.origin_session_id || r.session_id) !== sessionId) return false;
        if (r.status !== 'pending' && r.status !== 'expired') return false;

        if (toolCallId && r.tool_call_id === toolCallId) return true;
        if (parsedArgs?.hitl_id && r.hitl_id === parsedArgs.hitl_id) return true;

        if (prompt && r.request?.prompt) {
            const p1 = String(prompt).trim();
            const p2 = String(r.request.prompt).trim();
            if (p1 === p2) return true;
            if (p1.includes(p2) || p2.includes(p1)) return true;
        }
        return false;
    });

    if (!pendingRequest && sessionStatus === 'waiting_for_human') {
        const pendingForSession = hitlRequests?.filter(req => (req.origin_session_id || req.session_id) === sessionId && req.status === 'pending') || [];
        if (pendingForSession.length === 1) {
            pendingRequest = pendingForSession[0];
        }
    }

    let resolution = null;
    if (output) {
        try {
            resolution = typeof output.content === 'string' ? JSON.parse(output.content) : output.content;
        } catch (e) {
            if (output.content?.includes("Decision:")) {
                const decisionLine = output.content.split('\n').find(l => l.includes("Decision:"));
                const decision = decisionLine ? decisionLine.split(':')[1].trim() : output.content;
                resolution = { decision };
            } else {
                resolution = { decision: output.content };
            }
        }
    }
    // Fall back to locally tracked resolution when backend output hasn't arrived yet
    if (!resolution && localResolution) {
        resolution = localResolution;
    }

    const isPending = !!pendingRequest && pendingRequest.status === 'pending' && !output;
    const isExpired = !!pendingRequest && pendingRequest.status === 'expired' && !output;

    const handleAction = async (decision, comment = "", extraFields = {}) => {
        if (!isPending) return;
        setSubmittingAction(decision);
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

            await onResolve(hitlIdToResolve, {
                decision,
                comment,
                ...extraFields,
                tool_call_id: toolCallId
            });
            const label = tool_permission_options?.find(o => o.id === decision)?.label;
            setLocalResolution({ decision: label || decision });
            setUserInput('');
        } catch (e) {
            console.error("Resolution error:", e);
            alert(`Failed to submit decision: ${e.message}`);
        } finally {
            setSubmittingAction(null);
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
                {submittingAction !== null && (
                    <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10px', color: '#3b82f6', fontWeight: 600 }}>
                        <div style={{ width: '10px', height: '10px', border: '2px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                        <span>Processing...</span>
                    </div>
                )}
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
                            {(() => {
                                const dec = resolution.decision;
                                if (dec && tool_permission_options?.length) {
                                    const match = tool_permission_options.find(o => o.id === dec);
                                    if (match?.label) return match.label;
                                }
                                return dec || JSON.stringify(resolution);
                            })()}
                        </div>
                    </div>
                ) : (isPending || submittingAction !== null) ? (
                    <div className="hitl-actions">
                        {type === 'approve_reject' && (
                            <div style={{ display: 'flex', gap: '10px', width: '100%' }}>
                                <button
                                    className="hitl-btn"
                                    onClick={() => handleAction('approved')}
                                    disabled={submittingAction !== null}
                                    style={{
                                        flex: 1,
                                        background: submittingAction === 'approved' ? '#10b981' : (submittingAction !== null ? '#f1f5f9' : '#10b981'),
                                        color: (submittingAction !== null && submittingAction !== 'approved') ? '#94a3b8' : 'white',
                                        border: 'none',
                                        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px'
                                    }}
                                >
                                    {submittingAction === 'approved' && <div className="hitl-spinner" style={{ width: '12px', height: '12px', borderTopColor: 'white' }} />}
                                    Approve
                                </button>
                                <button
                                    className="hitl-btn"
                                    onClick={() => handleAction('rejected')}
                                    disabled={submittingAction !== null}
                                    style={{
                                        flex: 1,
                                        background: submittingAction === 'rejected' ? '#ef4444' : (submittingAction !== null ? '#f1f5f9' : 'transparent'),
                                        color: submittingAction === 'rejected' ? 'white' : (submittingAction !== null ? '#94a3b8' : '#ef4444'),
                                        border: submittingAction === 'rejected' ? 'none' : '1px solid #ef4444'
                                    }}
                                >
                                    {submittingAction === 'rejected' && <div className="hitl-spinner" style={{ width: '12px', height: '12px', borderTopColor: 'white' }} />}
                                    Reject
                                </button>
                            </div>
                        )}

                        {type === 'tool_permission' && (() => {
                            const structuredOpts = tool_permission_options || [];
                            const colorMap = {
                                'reject': '#ef4444',
                                'approve_once': '#10b981',
                                'approve_session': '#3b82f6',
                                'approve_permanent': '#6366f1',
                            };
                            const buttons = structuredOpts.length > 0 ? structuredOpts : [
                                { id: 'approve_once', label: 'Allow Once', primary: true },
                                { id: 'approve_session', label: 'For Session' },
                                { id: 'approve_permanent', label: 'Always' },
                                { id: 'reject', label: 'Reject' },
                            ];
                            return (
                                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                    {buttons.map(btn => (
                                        <button
                                            key={btn.id}
                                            disabled={submittingAction !== null}
                                            onClick={() => handleAction(btn.id, "", {
                                                grant_scope: btn.scope || undefined,
                                                permission_pattern: btn.pattern || undefined,
                                            })}
                                            className="hitl-btn"
                                            style={{
                                                fontSize: '12px',
                                                padding: '6px 12px',
                                                background: submittingAction === btn.id ? (colorMap[btn.id] || '#3b82f6') : (submittingAction !== null ? '#f1f5f9' : (btn.primary ? (colorMap[btn.id] || '#3b82f6') : 'transparent')),
                                                color: submittingAction === btn.id ? 'white' : (submittingAction !== null ? '#94a3b8' : (btn.primary ? 'white' : (colorMap[btn.id] || '#3b82f6'))),
                                                border: btn.primary ? 'none' : `1px solid ${colorMap[btn.id] || '#3b82f6'}40`
                                            }}
                                        >
                                            {submittingAction === btn.id && <div className="hitl-spinner" style={{ width: '10px', height: '10px', borderTopColor: 'white', marginRight: '4px' }} />}
                                            {btn.label || btn.id}
                                        </button>
                                    ))}
                                </div>
                            );
                        })()}

                        {(type === 'choose' || type === 'options') && optionsArray.length > 0 && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', width: '100%' }}>
                                {optionsArray.map((opt, i) => (
                                    <button
                                        key={i}
                                        className="hitl-btn"
                                        onClick={() => handleAction(opt)}
                                        disabled={submittingAction !== null}
                                        style={{
                                            textAlign: 'left', justifyContent: 'flex-start',
                                            background: submittingAction === opt ? '#eff6ff' : (submittingAction !== null ? '#f8fafc' : '#ffffff'),
                                            border: '1px solid #e2e8f0',
                                            color: submittingAction === opt ? '#3b82f6' : (submittingAction !== null ? '#94a3b8' : '#475569')
                                        }}
                                    >
                                        {submittingAction === opt && <div className="hitl-spinner" style={{ width: '12px', height: '12px', borderTopColor: '#3b82f6', marginRight: '8px' }} />}
                                        {opt}
                                    </button>
                                ))}
                            </div>
                        )}

                        {(type === 'provide_input' || ((type === 'choose' || type === 'options') && optionsArray.length === 0) || (!['approve_reject', 'tool_permission', 'choose', 'options', 'notify'].includes(type))) && (
                            <div className="hitl-input-container" style={{ width: '100%', display: 'flex', gap: '8px' }}>
                                <input
                                    className="hitl-input"
                                    placeholder="Type your response..."
                                    value={userInput}
                                    onChange={e => setUserInput(e.target.value)}
                                    onKeyDown={e => {
                                        if (e.key === 'Enter' && userInput.trim() && !submittingAction) {
                                            handleAction(userInput.trim());
                                        }
                                    }}
                                    disabled={submittingAction !== null}
                                />
                                <button
                                    className="hitl-btn"
                                    onClick={() => handleAction(userInput.trim())}
                                    disabled={!userInput.trim() || submittingAction !== null}
                                    style={{ background: '#3b82f6', color: 'white', border: 'none', minWidth: '80px' }}
                                >
                                    {submittingAction !== null ? <div className="hitl-spinner" style={{ width: '12px', height: '12px', borderTopColor: 'white' }} /> : 'Send'}
                                </button>
                            </div>
                        )}

                        {type === 'notify' && (
                            <button
                                className="hitl-btn"
                                onClick={() => handleAction('acknowledged')}
                                disabled={submittingAction !== null}
                                style={{ width: '100%', background: '#3b82f6', color: 'white', border: 'none' }}
                            >
                                {submittingAction === 'acknowledged' ? <div className="hitl-spinner" style={{ width: '12px', height: '12px', borderTopColor: 'white' }} /> : 'Acknowledge'}
                            </button>
                        )}
                    </div>
                ) : null}
            </div>
        </div>
    );
};

const ExcalidrawPreview = ({ content }) => {
    const [svgNode, setSvgNode] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        let isRendered = false;
        const render = async () => {
            try {
                const parsed = JSON.parse(content);
                const { exportToSvg } = await import('@excalidraw/excalidraw');

                const svg = await exportToSvg({
                    elements: parsed.elements || [],
                    appState: {
                        ...(parsed.appState || {}),
                        exportBackground: true,
                        exportWithDarkMode: false,
                    },
                    files: parsed.files || {},
                });

                // Keep the SVG responsive
                svg.classList.add('excalidraw-adaptive-svg');
                svg.style.width = '100%';
                svg.style.height = 'auto'; // Will scale proportionally
                svg.style.maxWidth = '100%';
                if (!isRendered) {
                    setSvgNode(svg);
                }
            } catch (err) {
                if (!isRendered) setError(err.message);
            }
        };
        render();
        return () => { isRendered = true; };
    }, [content]);

    if (error) return <div style={{ color: '#ef4444', padding: '20px', fontSize: '12px' }}>Failed to render Excalidraw: {error}</div>;
    if (!svgNode) return <div style={{ padding: '20px', color: '#9ca3af', textAlign: 'center', fontSize: '12px' }}>Rendering...</div>;

    return (
        <div
            style={{ width: '100%', display: 'flex', justifyContent: 'center', padding: '16px', boxSizing: 'border-box' }}
            ref={node => {
                if (node && svgNode) {
                    node.innerHTML = '';
                    node.appendChild(svgNode);
                }
            }}
        />
    );
};

const InlineDocumentPreview = ({ fileUrl, fileName }) => {
    const [content, setContent] = useState(null);
    useEffect(() => {
        fetch(fileUrl).then(r => r.text()).then(setContent).catch(console.error);
    }, [fileUrl]);

    if (!content) return <div style={{ padding: '20px', color: '#9ca3af', textAlign: 'center', fontSize: '12px' }}>Loading diagram...</div>;

    if (fileName.endsWith('.excalidraw')) {
        return <ExcalidrawPreview content={content} />;
    }

    if (fileName.endsWith('.mermaid') || fileName.endsWith('.mmd')) {
        return <MermaidPreview chart={content} style={{ height: 'auto' }} />;
    }
    return null;
};

export const FileTimelinePreview = ({ file, sessionId, onPreview }) => {

    const effectiveMime = (mime, path) => {
        if (mime && mime !== 'application/octet-stream' && mime !== 'binary/octet-stream') return mime;
        const ext = path?.split('.').pop().toLowerCase();
        const map = {
            'mp4': 'video/mp4', 'webm': 'video/webm', 'mov': 'video/quicktime',
            'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'gif': 'image/gif', 'svg': 'image/svg+xml', 'webp': 'image/webp',
            'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg',
            'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'ppt': 'application/vnd.ms-powerpoint', 'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'mermaid': 'text/x-mermaid', 'mmd': 'text/x-mermaid',
            'excalidraw': 'application/json',
            'mindmap': 'application/json'
        };
        return map[ext] || mime;
    };

    const isDir = file.mime_type === 'inode/directory';
    const mime = effectiveMime(file.mime_type, file.file_path);
    const isImage = !isDir && mime?.startsWith('image/');
    const isVideo = !isDir && mime?.startsWith('video/');
    const isAudio = !isDir && mime?.startsWith('audio/');
    const ext = isDir ? 'DIRECTORY' : (file.file_path?.split('.').pop().toUpperCase() || 'FILE');

    const fileUrl = `/api/sessions/${sessionId}/files/${file.file_path}`;

    const isExcalidraw = file.file_name?.endsWith('.excalidraw');
    const isMermaid = file.file_name?.endsWith('.mermaid') || file.file_name?.endsWith('.mmd');
    const hasInlinePreview = isExcalidraw || isMermaid;

    return (
        <div className="file-timeline-preview-card">
            <div className="file-timeline-preview-header">
                <div className="file-timeline-info">
                    <span className="file-timeline-name">{file.file_name}</span>
                    <span className="file-timeline-size">{isDir ? '(Directory)' : `(${(file.size / 1024).toFixed(1)} KB)`}</span>
                </div>
                <button className="file-timeline-open-btn" onClick={() => onPreview(file)}>
                    Full Preview
                </button>
            </div>

            <div className="file-timeline-content">
                {isImage && (
                    <img src={fileUrl} alt={file.file_name} className="file-timeline-img" onClick={() => onPreview(file)} />
                )}
                {isVideo && (
                    <video controls className="file-timeline-video">
                        <source src={fileUrl} type={mime} />
                    </video>
                )}
                {isAudio && (
                    <audio controls className="file-timeline-audio">
                        <source src={fileUrl} type={mime} />
                    </audio>
                )}
                {hasInlinePreview && (
                    <InlineDocumentPreview fileUrl={fileUrl} fileName={file.file_name} />
                )}
                {!isImage && !isVideo && !isAudio && !hasInlinePreview && (
                    <div className="file-timeline-placeholder" onClick={() => onPreview(file)}>
                        {isDir ? (
                            <Folder size={32} style={{ color: '#94a3b8', marginBottom: '8px' }} />
                        ) : (
                            <ChevronRight size={32} style={{ color: '#94a3b8', marginBottom: '8px' }} />
                        )}
                        <span>{isDir ? 'Click to View Directory' : `Click to Preview ${ext}`}</span>
                    </div>
                )}
            </div>
        </div>
    );
};


export const MessageItem = memo(({ message, agentName, hitlRequests, onResolve, sessionId, sessionStatus, onPreviewFile }) => {
    if (message.role === 'file_event') {
        const fileData = message.file || (message.content ? JSON.parse(message.content) : null);
        if (!fileData) return null;
        return (
            <div className="message-row message-row-agent">
                <div className="message-avatar avatar-agent">
                    <Bot size={16} />
                </div>
                <div className="message-content-wrapper wrapper-agent">
                    <div className="message-sender-name">
                        <span>{`Agent: ${agentName || 'Agent'}`}</span>
                    </div>
                    <FileTimelinePreview
                        file={fileData}
                        sessionId={sessionId}
                        onPreview={onPreviewFile}
                    />
                </div>
            </div>
        );
    }

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
                    <span>{isUser ? 'You' : `Agent: ${agentName || 'Agent'}`}</span>
                    {(message.created_at || message.timestamp) && (
                        <span className="message-time">
                            {new Date(message.created_at || message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                    )}
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

                            const hitlMatch = hitlRequests?.find(r => r.tool_call_id === tc.id);
                            const isHitl = tc.name === 'request_human_input' || tc.function?.name === 'request_human_input' || !!hitlMatch;

                            if (isHitl) {
                                let hitlArgs = tc.function?.arguments || tc.arguments || tc.args;
                                if (hitlMatch && hitlMatch.request) {
                                    try {
                                        hitlArgs = typeof hitlMatch.request === 'string' ? JSON.parse(hitlMatch.request) : hitlMatch.request;
                                    } catch (e) {
                                        hitlArgs = hitlMatch.request;
                                    }
                                }

                                return (
                                    <HitlHistoryCard
                                        key={i}
                                        args={hitlArgs}
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
            </div>
        </div>
    );
});

