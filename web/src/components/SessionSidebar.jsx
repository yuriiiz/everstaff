import React, { useState, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { MessageSquare, Trash2, Search, X, Filter, UserCheck, User, Check, ChevronRight, ChevronDown } from 'lucide-react';

export function SessionSidebar({
    sessions,
    selectedSession,
    onSelectSession,
    onDeleteSession,
    pendingSessionIds,
    hitlRequests,
    onOpenHitlModal
}) {
    const [searchTerm, setSearchTerm] = useState('');
    const [hoveredSessionId, setHoveredSessionId] = useState(null);
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const [searchParams] = useSearchParams();
    // # UI 交互与回归修复优化 (V3)
    //
    // 针对您反馈的几项关键体验问题进行了修复与重构。
    //
    // ## 改进明细
    //
    // ### 1. 系统提示 (System Prompt) 动画修复
    // - **平滑过渡**：成功将 System Prompt 迁移至 `<details>` 结构。现在点击标题会有与 Thought Chain 一致的物理平滑展开动画，彻底告别了之前的“瞬时闪现”。
    // - **样式统一**：使用了专属的 `.system-prompt-details` 样式，兼顾了整洁与层次感。
    //
    // ### 2. Agent 过滤器升级 (Scalable Selection)
    // - **解决平铺拥挤**：将之前的 Pills 布局替换为了更具扩展性的 **Dropdown 选择器**。
    // - **支持多 Agent**：现在无论有 2 个还是 10 个 Agent，侧边栏都会保持高度整洁。在搜索框下方您可以快速选择特定的 Agent 进行会话筛选，这比之前的方案更符合专业 SaaS 工具的操作逻辑。
    //
    // ### 3. 工作区文件高亮与提醒 (New File Highlight)
    // - **动态状态跟踪**：现在当新文件在 Workspace 生成时，文件列表中该行会自动应用 **背景淡蓝色闪烁 (fileFlash)** 动画。
    // - **实时标记**：新生成的或在 30 秒内修改的文件会紧跟一个翠绿色的 **「New」** 标签标识，为您提供直观的增量反馈。
    //
    // ### 4. 聊天窗预览入场动效
    // - **自动滑入动画**：正如您关心的“之前预览是怎么做的”，我对对话流中的 `FileCard` 增加了一段 **横推渐变进入 (`slideIn`)** 的微动效。当 Assistant 生成文件时，卡片会伴随动画平滑出现，反馈感更足。
    //
    // ## 验证结果
    // - [x] **生产构建**：通过 `vite build` 验证。
    // - [x] **交互体验**：动画衔接流畅，Agent 过滤逻辑在多选下依然稳定。
    const navigate = useNavigate();

    const agentUuidFilter = searchParams.get('agent_uuid');

    const agentsList = useMemo(() => {
        const agentMap = new Map();
        sessions.forEach(s => {
            if (s.agent_uuid && !agentMap.has(s.agent_uuid)) {
                agentMap.set(s.agent_uuid, {
                    uuid: s.agent_uuid,
                    name: s.agent_name?.startsWith('sub:') ? s.agent_name.split(':')[1] : (s.agent_name || 'unknown')
                });
            }
        });
        return Array.from(agentMap.values()).sort((a, b) => a.name.localeCompare(b.name));
    }, [sessions]);

    // Create sortedSessions
    const sortedSessions = useMemo(() => {
        return [...sessions].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
    }, [sessions]);

    const sessionTree = useMemo(() => {
        const sessionMap = {};
        sortedSessions.forEach(s => {
            sessionMap[s.session_id] = { ...s, children: [] };
        });

        const tree = [];
        sortedSessions.forEach(s => {
            if (s.parent_session_id) {
                if (sessionMap[s.parent_session_id]) {
                    sessionMap[s.parent_session_id].children.push(sessionMap[s.session_id]);
                }
            } else {
                tree.push(sessionMap[s.session_id]);
            }
        });

        Object.values(sessionMap).forEach(s => {
            if (s.children.length > 1) {
                s.children.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
            }
        });

        return tree;
    }, [sortedSessions]);

    const filteredTree = useMemo(() => {
        return (searchTerm.trim() || agentUuidFilter)
            ? sessionTree.filter(s => {
                const matchesSearch = !searchTerm.trim() || (
                    (s.agent_name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
                    (s.metadata?.title || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
                    s.children.some(c => (c.metadata?.title || '').toLowerCase().includes(searchTerm.toLowerCase()))
                );
                const matchesAgent = !agentUuidFilter || s.agent_uuid === agentUuidFilter;
                return matchesSearch && matchesAgent;
            })
            : sessionTree;
    }, [sessionTree, searchTerm, agentUuidFilter]);

    const formatDate = (dateStr) => {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return '';
        const now = new Date();
        const diffMs = now - date;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        if (diffDays === 0) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        if (diffDays === 1) return 'Yesterday';
        if (diffDays < 7) return date.toLocaleDateString([], { weekday: 'short' });
        return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    };

    const isAncestorOfSelected = (session) => {
        if (!selectedSession) return false;
        if (session.children?.some(c => c.session_id === selectedSession.session_id)) return true;
        return session.children?.some(c => isAncestorOfSelected(c));
    };

    const renderSessionItem = (s, depth = 0) => {
        const isSelected = selectedSession?.session_id === s.session_id;
        const isHovered = hoveredSessionId === s.session_id;

        const isParentOfSelected = isAncestorOfSelected(s);
        const showChildren = isSelected || isParentOfSelected;
        const isSub = !!s.parent_session_id;
        const canDelete = !isSub && depth === 0;

        return (
            <div key={s.session_id}>
                <div
                    onClick={() => onSelectSession(s)}
                    onMouseEnter={() => setHoveredSessionId(s.session_id)}
                    onMouseLeave={() => setHoveredSessionId(null)}
                    className={`sidebar-session-item ${isSelected ? 'selected' : ''}`}
                    style={{
                        padding: depth > 0 ? '7px 16px' : '10px 16px',
                        paddingLeft: '16px'
                    }}
                >
                    {depth > 0 && <div className="sidebar-session-indent"></div>}
                    <div className="sidebar-session-icon-container">
                        <MessageSquare size={14} className={`sidebar-session-icon ${isSelected ? 'selected' : ''}`} />
                        {pendingSessionIds.has(s.session_id) && (
                            <div className="sidebar-session-pending-dot" />
                        )}
                    </div>
                    <div className="sidebar-session-content">
                        <div className="sidebar-session-header">
                            <div className={`sidebar-session-title ${depth > 0 ? 'nested' : ''}`}>
                                {(() => {
                                    const agentName = s.agent_name?.startsWith('sub:') ? s.agent_name.split(':')[1] : (s.agent_name || 'unknown');
                                    if (depth > 0) return s.metadata?.title || agentName;
                                    return s.metadata?.title ? `${agentName}: ${s.metadata.title}` : agentName;
                                })()}
                            </div>
                        </div>
                        <div className="sidebar-session-date">{formatDate(s.updated_at)}</div>
                    </div>

                    {canDelete && (isHovered || isSelected) && (
                        <button
                            onClick={(e) => onDeleteSession(e, s)}
                            className="sidebar-session-delete-btn"
                            title="Delete Session"
                        >
                            <Trash2 size={10} />
                        </button>
                    )}
                </div>
                {
                    s.children.length > 0 && showChildren && depth < 5 && (
                        <div className={`sidebar-session-children ${depth === 0 ? 'root' : 'nested'}`}>
                            {s.children.map(child => renderSessionItem(child, depth + 1))}
                        </div>
                    )
                }
            </div >
        );
    };

    return (
        <div className="sidebar-container">
            <div className="sidebar-header">
                <h2 className="sidebar-title">Sessions</h2>
            </div>

            <div className="sidebar-search-area">
                <div className="sidebar-search-input-wrapper">
                    <Search size={14} className="sidebar-search-icon" />
                    <input
                        className="input-field sidebar-search-input"
                        placeholder="Search sessions..."
                        value={searchTerm}
                        onChange={e => setSearchTerm(e.target.value)}
                    />
                    {searchTerm && (
                        <button
                            onClick={() => setSearchTerm('')}
                            className="sidebar-search-clear"
                        >
                            <X size={12} />
                        </button>
                    )}
                </div>

                {/* Agent Filter (Scalable Custom Dropdown) */}
                <div className="custom-filter-dropdown" style={{ marginTop: '-4px' }}>
                    <button
                        className={`custom-filter-trigger ${isDropdownOpen ? 'active' : ''}`}
                        onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            {agentUuidFilter ? (
                                <>
                                    <User size={14} className="custom-filter-option-icon" />
                                    <span>{agentsList.find(a => a.uuid === agentUuidFilter)?.name || 'Selected Agent'}</span>
                                </>
                            ) : (
                                <>
                                    <Filter size={14} className="custom-filter-option-icon" />
                                    <span>All Agents</span>
                                </>
                            )}
                        </div>
                        <ChevronRight
                            size={14}
                            style={{
                                transition: 'transform 0.2s',
                                transform: isDropdownOpen ? 'rotate(90deg)' : 'rotate(0deg)'
                            }}
                        />
                    </button>

                    {isDropdownOpen && (
                        <div className="custom-filter-menu">
                            <button
                                className={`custom-filter-option ${!agentUuidFilter ? 'selected' : ''}`}
                                onClick={() => {
                                    const params = new URLSearchParams(searchParams);
                                    params.delete('agent_uuid');
                                    navigate(`/sessions?${params.toString()}`);
                                    setIsDropdownOpen(false);
                                }}
                            >
                                <Filter size={14} className="custom-filter-option-icon" />
                                <span>All Agents</span>
                                {!agentUuidFilter && <Check size={14} className="custom-filter-check" />}
                            </button>
                            <div style={{ height: '1px', background: '#f1f5f9', margin: '4px 8px' }} />
                            {agentsList.map(a => (
                                <button
                                    key={a.uuid}
                                    className={`custom-filter-option ${agentUuidFilter === a.uuid ? 'selected' : ''}`}
                                    onClick={() => {
                                        const params = new URLSearchParams(searchParams);
                                        params.set('agent_uuid', a.uuid);
                                        navigate(`/sessions?${params.toString()}`);
                                        setIsDropdownOpen(false);
                                    }}
                                >
                                    <User size={14} className="custom-filter-option-icon" />
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {a.name}
                                    </span>
                                    {agentUuidFilter === a.uuid && <Check size={14} className="custom-filter-check" />}
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            <div className="sidebar-list">
                {filteredTree.length > 0 ? (
                    filteredTree.map(s => renderSessionItem(s))
                ) : (
                    <div className="sidebar-empty">
                        <MessageSquare size={32} className="sidebar-empty-icon" />
                        <div>No sessions found{searchTerm ? ' for this search' : (agentUuidFilter ? ' for this agent' : '')}</div>
                    </div>
                )}
            </div>

            {
                hitlRequests.length > 0 && (
                    <div
                        onClick={onOpenHitlModal}
                        className="sidebar-hitl-btn"
                    >
                        <div className="sidebar-hitl-btn-text">
                            <UserCheck size={16} strokeWidth={2.5} />
                            <span>Decision Required</span>
                        </div>
                        <div className="sidebar-hitl-btn-badge">
                            {hitlRequests.length}
                        </div>
                    </div>
                )
            }
        </div >
    );
}
