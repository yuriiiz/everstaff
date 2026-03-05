import React from 'react';
import { Cpu, Folder } from 'lucide-react';
import FileBrowser from './FileBrowser';

export function SessionDetails({
    selectedSession,
    messages,
    availableAgents,
    config,
    tokenUsage,
    liveTokenCalls,
    newFilesCount,
    setNewFilesCount,
    fileRefreshTrigger,
    onPreviewFile
}) {
    // Calculate current usage based on message content
    const calculateTokens = (msgs) => {
        let totalTokens = 0;
        const systemPrompt = selectedSession?.metadata?.system_prompt || '';
        const allText = msgs.reduce((acc, m) => {
            return acc + (m.content || '') + (m.thinking || '') + (m.tool_calls ? JSON.stringify(m.tool_calls) : '');
        }, systemPrompt);

        for (let char of allText) {
            if (char.charCodeAt(0) <= 127) {
                totalTokens += 0.3;
            } else {
                totalTokens += 0.6;
            }
        }
        return Math.floor(totalTokens);
    };

    const currentUsage = calculateTokens(messages || []);
    const usedModels = new Set();
    const md = selectedSession?.metadata || {};
    [...(md.own_calls || []), ...(md.children_calls || [])].forEach(c => {
        if (c.model_id) usedModels.add(c.model_id);
    });

    if (usedModels.size === 0 && config?.model_mappings && selectedSession) {
        const agentInfo = availableAgents?.find(a => a.agent_name === selectedSession.agent_name);
        const kind = agentInfo?.adviced_model_kind || 'smart';
        const mapping = config.model_mappings[kind];
        if (mapping) usedModels.add(mapping.model_id);
    }

    const own = (liveTokenCalls && liveTokenCalls.length > 0) ? liveTokenCalls : (md.own_calls || []);
    const children = md.children_calls || [];
    const aggOwn = {};
    const aggChild = {};

    own.forEach(c => {
        const m = c.model_id || 'Unknown';
        if (!aggOwn[m]) aggOwn[m] = { in: 0, out: 0, count: 0 };
        aggOwn[m].in += (c.input_tokens || 0);
        aggOwn[m].out += (c.output_tokens || 0);
        aggOwn[m].count += 1;
    });

    children.forEach(c => {
        const m = c.model_id || 'Unknown';
        if (!aggChild[m]) aggChild[m] = { in: 0, out: 0, count: 0 };
        aggChild[m].in += (c.input_tokens || 0);
        aggChild[m].out += (c.output_tokens || 0);
        aggChild[m].count += 1;
    });

    if (!selectedSession) return null;

    return (
        <div className="session-details-panel">
            {/* Scrollable Details Section */}
            <div className="session-details-scrollable">
                <div className="session-details-title">Session Details</div>
                <div className="session-details-content">
                    <div className="detail-card">
                        <div className="detail-card-title">Agent Name</div>
                        <div className="detail-card-value">{selectedSession.agent_name}</div>
                    </div>
                    <div className="detail-card">
                        <div className="detail-card-title">Session Title</div>
                        <div className="detail-card-value">{selectedSession.metadata?.title || 'Untitled Session'}</div>
                    </div>
                    <div className="detail-card">
                        <div className="detail-card-title">Session ID</div>
                        <div className="detail-card-value detail-value-mono">{selectedSession.session_id}</div>
                    </div>

                    {/* Context Window */}
                    <div className="detail-card detail-card-flex">
                        <div className="detail-card-header">
                            <Cpu size={14} className="detail-icon" />
                            <div className="detail-card-title" style={{ marginBottom: 0 }}>Context Window</div>
                        </div>

                        {usedModels.size === 0 ? (
                            <div className="detail-empty">No model data</div>
                        ) : (
                            Array.from(usedModels).map(modelId => {
                                let maxTokens = 128000;
                                if (config?.model_mappings) {
                                    const mapping = Object.values(config.model_mappings).find(m => m.model_id === modelId);
                                    if (mapping) maxTokens = mapping.max_tokens;
                                }
                                const percent = Math.min(100, Math.floor((currentUsage / maxTokens) * 100));

                                return (
                                    <div key={modelId} className="model-usage-item">
                                        <div className="usage-progress-circle">
                                            <svg width="36" height="36" viewBox="0 0 36 36">
                                                <circle cx="18" cy="18" r="15" fill="none" stroke="#e2e8f0" strokeWidth="4" />
                                                <circle cx="18" cy="18" r="15" fill="none"
                                                    stroke={percent > 80 ? '#ef4444' : percent > 50 ? '#f59e0b' : '#3b82f6'}
                                                    strokeWidth="4"
                                                    strokeDasharray={`${2 * Math.PI * 15}`}
                                                    strokeDashoffset={`${2 * Math.PI * 15 * (1 - percent / 100)}`}
                                                    strokeLinecap="round"
                                                    transform="rotate(-90 18 18)"
                                                    className="usage-circle-progress"
                                                />
                                            </svg>
                                            <div className="usage-progress-text">{percent}%</div>
                                        </div>

                                        <div className="usage-details">
                                            <div className="usage-model-id" title={modelId}>{modelId}</div>
                                            <div className="usage-stats">
                                                <span>current <strong>{currentUsage < 10000 ? (currentUsage / 1000).toFixed(1) : Math.floor(currentUsage / 1000)}K</strong></span>
                                                <span className="usage-separator">/</span>
                                                <span>max <strong>{Math.floor(maxTokens / 1000)}K</strong></span>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })
                        )}
                    </div>

                    {typeof tokenUsage === 'number' && tokenUsage > 0 && (
                        <div className="detail-card detail-card-flex">
                            <div className="detail-card-title">Token Usage</div>

                            <div className="token-usage-container">
                                {Object.keys(aggOwn).length > 0 && (
                                    <div className="token-usage-section">
                                        <div className="token-usage-header">
                                            <div className="token-usage-dot" />
                                            <div className="token-usage-title">Agent Calls</div>
                                        </div>
                                        {Object.entries(aggOwn).map(([modelId, stats]) => (
                                            <div key={`own-${modelId}`} className="token-stats-item">
                                                <div className="token-stats-header">
                                                    <div className="token-stats-model">{modelId}</div>
                                                    <div className="token-stats-count">{stats.count}x</div>
                                                </div>
                                                <div className="token-stats-grid">
                                                    <div className="token-stats-col">
                                                        <span className="token-stats-label">Input</span>
                                                        <span className="token-stats-value">{(stats.in || 0).toLocaleString()}</span>
                                                    </div>
                                                    <div className="token-stats-col">
                                                        <span className="token-stats-label">Output</span>
                                                        <span className="token-stats-value">{(stats.out || 0).toLocaleString()}</span>
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}

                                {Object.keys(aggChild).length > 0 && (
                                    <div className="token-usage-section">
                                        <div className="token-usage-header">
                                            <div className="token-usage-dot" />
                                            <div className="token-usage-title">Sub-Agent Calls</div>
                                        </div>
                                        {Object.entries(aggChild).map(([modelId, stats]) => (
                                            <div key={`child-${modelId}`} className="token-stats-item">
                                                <div className="token-stats-header">
                                                    <div className="token-stats-model">{modelId}</div>
                                                    <div className="token-stats-count">{stats.count}x</div>
                                                </div>
                                                <div className="token-stats-grid">
                                                    <div className="token-stats-col">
                                                        <span className="token-stats-label">Input</span>
                                                        <span className="token-stats-value">{(stats.in || 0).toLocaleString()}</span>
                                                    </div>
                                                    <div className="token-stats-col">
                                                        <span className="token-stats-label">Output</span>
                                                        <span className="token-stats-value">{(stats.out || 0).toLocaleString()}</span>
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <div className="token-total-container">
                                <div className="token-total-align">
                                    <div className="detail-card-title">Total Tokens</div>
                                    <div className="token-total-value">{tokenUsage.toLocaleString()}</div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Pinned Files Section at Bottom */}
            <div className="files-panel">
                <div
                    onClick={() => setNewFilesCount(0)}
                    className={`files-panel-header ${newFilesCount > 0 ? 'has-new' : ''}`}
                >
                    <div className="files-panel-title">
                        <Folder size={14} className="files-panel-icon" />
                        <span>Workspace Files</span>
                    </div>
                    {newFilesCount > 0 && (
                        <div className="new-files-badge">
                            <div className="new-files-dot" />
                            <span className="new-files-text">{newFilesCount} NEW</span>
                        </div>
                    )}
                </div>
                <div className="files-panel-content">
                    <FileBrowser sessionId={selectedSession.session_id} onPreview={onPreviewFile} refreshTrigger={fileRefreshTrigger} />
                </div>
            </div>
            <style>{`
                @keyframes pulse-dot {
                    0% { transform: scale(1); opacity: 1; }
                    50% { transform: scale(1.3); opacity: 0.6; }
                    100% { transform: scale(1); opacity: 1; }
                }
            `}</style>
        </div>
    );
}

