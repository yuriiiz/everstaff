import { useState, useEffect, useRef, memo, useMemo, useCallback } from 'react';
import { useSearchParams, useParams, useNavigate } from 'react-router-dom';
import { MessageSquare, User, Trash2, Send, ChevronRight, ChevronDown, Terminal, Cpu, Bot, UserCheck, Check, Search, X, Sparkles, Zap, Filter, Folder, Square, Settings } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { HitlPanel } from './HitlComponents';
import FileCard from '../components/FileCard';
import FilePreviewModal from '../components/FilePreviewModal';
import FileBrowser from '../components/FileBrowser';

import { ChatInput, CREATOR_SUGGESTIONS } from '../components/ChatInput';
import { MessageItem, HitlHistoryCard } from '../components/ChatMessages';
import { SessionSidebar } from '../components/SessionSidebar';
import { SessionDetails } from '../components/SessionDetails';

export default function SessionStore() {
    const [sessions, setSessions] = useState([]);
    const [selectedSession, setSelectedSession] = useState(null);
    const [messages, setMessages] = useState([]);
    const [isConnected, setIsConnected] = useState(false);
    const [hoveredSessionId, setHoveredSessionId] = useState(null);
    const [availableAgents, setAvailableAgents] = useState([]); // List of active agents
    const [isProcessing, setIsProcessing] = useState(false);
    const [statusContent, setStatusContent] = useState('');
    const [tokenUsage, setTokenUsage] = useState(0);
    const [inputTokens, setInputTokens] = useState(0);
    const [outputTokens, setOutputTokens] = useState(0);
    const [liveTokenCalls, setLiveTokenCalls] = useState([]);  // accumulated during streaming
    const [showSystemPrompt, setShowSystemPrompt] = useState(false);
    const [isConnecting, setIsConnecting] = useState(false);
    const [reconnectTrigger, setReconnectTrigger] = useState(0);
    const [loadingAgents, setLoadingAgents] = useState(true);
    const [hitlRequests, setHitlRequests] = useState([]);
    const [searchTerm, setSearchTerm] = useState('');
    const [config, setConfig] = useState(null);
    const [loadingConfig, setLoadingConfig] = useState(true);
    const [newFilesCount, setNewFilesCount] = useState(0);
    const [fileRefreshTrigger, setFileRefreshTrigger] = useState(0);
    const wsRef = useRef(null);
    const sseRef = useRef(null);
    const [isHitlModalOpen, setIsHitlModalOpen] = useState(false);
    const [previewFile, setPreviewFile] = useState(null);
    const scrollRef = useRef(null);
    const clientIdRef = useRef(crypto.randomUUID());
    const [searchParams] = useSearchParams();
    const { sessionId } = useParams();
    const navigate = useNavigate();

    useEffect(() => {
        fetchSessions();
        fetchAgents();
        fetchConfig();
    }, []);

    const fetchConfig = () => {
        setLoadingConfig(true);
        fetch('/api/config')
            .then(res => res.json())
            .then(data => {
                setConfig(data);
                setLoadingConfig(false);
            })
            .catch(err => {
                console.error('Failed to fetch config:', err);
                setLoadingConfig(false);
            });
    };

    // Unified sort logic: Roots descending by date, Subs ascending by date
    const sortedSessions = [...sessions].sort((a, b) => {
        const isSubA = !!a.parent_session_id;
        const isSubB = !!b.parent_session_id;
        const tsA = new Date(a.created_at || 0).getTime();
        const tsB = new Date(b.created_at || 0).getTime();

        if (isSubA !== isSubB) {
            return isSubA ? 1 : -1; // Roots first
        }
        // Roots: newest first (descending); Subs: oldest first (ascending)
        return isSubA ? (tsA - tsB) : (tsB - tsA);
    });

    // Unified synchronization of selectedSession with URL path/search parameters
    useEffect(() => {
        const targetId = sessionId || searchParams.get('session_id');
        const agentNameParam = searchParams.get('agent_name');
        const agentUuidParam = searchParams.get('agent_uuid');
        const statusParam = searchParams.get('status');

        // Case 0: Status-based triggers (e.g. from Dashboard)
        if (statusParam === 'waiting_for_human') {
            setIsHitlModalOpen(true);
        }

        // Case 1: Specific session ID requested
        if (targetId) {
            if (targetId !== selectedSession?.session_id) {
                const found = sessions.find(s => s.session_id === targetId);
                if (found) {
                    console.log(`[debug] Selecting session from URL: ${targetId}`);
                    // Navigate is already true in URL, so just sync state
                    handleSelectSession(found, false);
                } else {
                    console.log(`[debug] Session ${targetId} not found in list yet.`);
                }
            }
            return;
        }

        // Case 2: New agent chat requested
        if (agentNameParam || agentUuidParam) {
            // Resolve display name if we only have UUID or it's a built-in
            let displayAgentName = agentNameParam;
            if (agentUuidParam === 'builtin_agent_creator') displayAgentName = 'Agent Architect';
            else if (agentUuidParam === 'builtin_skill_creator') displayAgentName = 'Skill Forge';
            else if (!displayAgentName && agentUuidParam && availableAgents.length > 0) {
                const agent = availableAgents.find(a => a.uuid === agentUuidParam);
                if (agent) displayAgentName = agent.agent_name;
            }

            const existingMatch = selectedSession && selectedSession.isNew &&
                (agentNameParam ? selectedSession.agent_name === agentNameParam : selectedSession.agent_uuid === agentUuidParam);

            if (existingMatch) {
                // Re-resolve display name if agents loaded after initial creation
                if (displayAgentName && selectedSession.agent_name === 'Agent' && displayAgentName !== 'Agent') {
                    setSelectedSession(prev => ({
                        ...prev,
                        agent_name: displayAgentName,
                        metadata: { ...prev.metadata, title: `New Chat with ${displayAgentName}` }
                    }));
                }
                return;
            }

            console.log(`[debug] Preparing pending session for agent: ${agentNameParam || agentUuidParam}`);

            const pendingSession = {
                agent_name: displayAgentName || 'Agent',
                agent_uuid: agentUuidParam,
                isNew: true,
                session_id: null,
                messages: [],
                metadata: { title: `New Chat with ${displayAgentName || 'Agent'}` }
            };
            setSelectedSession(pendingSession);
            setMessages([]);
            setIsConnected(false);
            return;
        }

        // Case 3: No specific session or agent, default to first available (State only, NO URL CHANGE)
        if (!selectedSession && sortedSessions.length > 0) {
            const topLevelSessions = sortedSessions.filter(s => !s.parent_session_id);
            const toSelect = topLevelSessions.length > 0 ? topLevelSessions[0] : sortedSessions[0];
            console.log(`[debug] No session in URL, selecting first sorted session for UI: ${toSelect?.session_id}`);
            handleSelectSession(toSelect, false); // DO NOT NAVIGATE
        }
    }, [sessionId, searchParams, sortedSessions.length, availableAgents.length]);

    // Update URL when session is selected manually
    const onSessionSelected = (session) => {
        if (session) {
            navigate(`/sessions/${session.session_id}`, { replace: true });
        } else {
            navigate('/sessions', { replace: true });
        }
    };

    const handleSelectSession = (session, shouldNavigate = true) => {
        setIsHitlModalOpen(false); // Always close modal when explicitly selecting a session (e.g. from Context link)
        setSelectedSession(session);
        setLiveTokenCalls([]);
        if (shouldNavigate) {
            onSessionSelected(session);
        }
        fetchMessages(session.session_id);
    };

    const connectingRef = useRef(false);

    // Global WebSocket for HITL events and session list refresh
    useEffect(() => {
        const _wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${_wsProto}//${window.location.host}/api/ws`);
        let refreshTimer = null;
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'hitl_request') {
                    // Directly populate from WS event (avoids race with /api/hitl fetch)
                    setHitlRequests(prev => {
                        if (prev.some(r => r.hitl_id === data.hitl_id)) return prev;
                        return [...prev, {
                            hitl_id: data.hitl_id,
                            session_id: data.session_id,
                            tool_call_id: data.tool_call_id || '',
                            status: 'pending',
                            prompt: data.prompt,
                            hitl_type: data.hitl_type,
                            options: data.options || [],
                            context: data.context || '',
                            tool_name: data.tool_name,
                            tool_args: data.tool_args,
                            request: {
                                type: data.hitl_type,
                                prompt: data.prompt,
                                options: data.options || [],
                                context: data.context || '',
                                tool_name: data.tool_name,
                                tool_args: data.tool_args,
                            },
                        }];
                    });
                }
                if (data.type === 'session_end') {
                    // Debounced session list refresh (picks up new sub-sessions)
                    if (refreshTimer) clearTimeout(refreshTimer);
                    refreshTimer = setTimeout(() => fetchSessions(), 300);
                }
            } catch (e) {
                console.error("Global WS error:", e);
            }
        };
        wsRef.current = ws;

        // Initial HITL fetch
        fetch('/api/hitl')
            .then(res => res.json())
            .then(data => setHitlRequests(data));

        return () => {
            if (refreshTimer) clearTimeout(refreshTimer);
            ws.close();
        };
    }, []);

    // Reset system prompt expansion when switching sessions
    useEffect(() => {
        if (selectedSession?.session_id) {
            setShowSystemPrompt(false);
        }
    }, [selectedSession?.session_id]);

    // Session WebSocket connection (Unified)
    useEffect(() => {
        if (!selectedSession?.session_id) return;

        const sessionId = selectedSession.session_id;
        if (wsRef.current) wsRef.current.close();

        setIsConnecting(true);
        // Using same /ws endpoint with query param
        const _wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${_wsProto}//${window.location.host}/api/ws?session_id=${sessionId}`);

        ws.onopen = () => {
            console.log(`[debug] WS Connected to session: ${sessionId}`);
            setIsConnected(true);
            setIsConnecting(false);
            // Refresh messages immediately on connection/reconnection to sync missed content
            fetchMessages(sessionId);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'message') {
                    setMessages(prev => [...prev, {
                        role: 'assistant',
                        content: data.content,
                        tool_calls: data.tool_calls || [],
                        timestamp: Date.now()
                    }]);
                    // Refresh metadata to update token usage on right panel
                    fetchMessages(sessionId);
                } else if (data.type === 'text_delta') {
                    setMessages(prev => {
                        const last = prev[prev.length - 1];
                        if (last && last.role === 'assistant' && last.streaming) {
                            return [...prev.slice(0, -1), { ...last, content: last.content + data.content }];
                        }
                        return [...prev, { role: 'assistant', content: data.content, streaming: true, created_at: new Date().toISOString() }];
                    });
                } else if (data.type === 'session_end') {
                    // Refresh metadata when interaction ends; clear live accumulator
                    setLiveTokenCalls([]);
                    fetchMessages(sessionId);
                    setMessages(prev => {
                        const last = prev[prev.length - 1];
                        if (last && last.streaming) {
                            return [...prev.slice(0, -1), { ...last, streaming: false }];
                        }
                        return prev;
                    });
                    setIsProcessing(false);
                    setStatusContent('');
                    setFileRefreshTrigger(prev => prev + 1);
                } else if (data.type === 'thinking_delta') {
                    setMessages(prev => {
                        const last = prev[prev.length - 1];
                        if (last && last.role === 'assistant' && last.streaming) {
                            return [...prev.slice(0, -1), { ...last, thinking: (last.thinking || '') + data.content }];
                        }
                        return [...prev, { role: 'assistant', thinking: data.content, streaming: true, created_at: new Date().toISOString(), content: '' }];
                    });
                } else if (data.type === 'turn_start') {
                    setIsProcessing(true);
                    setStatusContent('Thinking...');
                } else if (data.type === 'tool_call_start') {
                    setStatusContent(`Running: ${data.name}`);
                    // Add a pending tool call entry to the current streaming assistant message.
                    // If no streaming message exists (e.g. new turn starting with a tool call),
                    // create one — this prevents mixing TCs into the previous session's last message.
                    setMessages(prev => {
                        const pendingTC = {
                            id: `_streaming_${Date.now()}_${data.name}`,
                            name: data.name,
                            type: 'function',
                            function: { name: data.name, arguments: JSON.stringify(data.args || {}) },
                            _streaming: true,
                        };
                        for (let i = prev.length - 1; i >= 0; i--) {
                            if (prev[i].role === 'assistant' && prev[i].streaming) {
                                return [
                                    ...prev.slice(0, i),
                                    { ...prev[i], tool_calls: [...(prev[i].tool_calls || []), pendingTC] },
                                    ...prev.slice(i + 1),
                                ];
                            }
                        }
                        // No streaming assistant message found — start a new one
                        return [...prev, { role: 'assistant', content: '', streaming: true, tool_calls: [pendingTC], created_at: new Date().toISOString() }];
                    });
                } else if (data.type === 'tool_call_end') {
                    setStatusContent('');
                    // Mark the matching streaming tool call as completed with result
                    setMessages(prev => {
                        for (let i = prev.length - 1; i >= 0; i--) {
                            const msg = prev[i];
                            if (msg.role === 'assistant' && msg.tool_calls) {
                                // Find last streaming TC with matching name
                                let tcIdx = -1;
                                for (let j = msg.tool_calls.length - 1; j >= 0; j--) {
                                    if (msg.tool_calls[j]._streaming && msg.tool_calls[j].name === data.name) {
                                        tcIdx = j;
                                        break;
                                    }
                                }
                                if (tcIdx !== -1) {
                                    const updated = [...msg.tool_calls];
                                    updated[tcIdx] = { ...updated[tcIdx], _streaming: false };
                                    return [
                                        ...prev.slice(0, i),
                                        { ...msg, tool_calls: updated },
                                        ...prev.slice(i + 1),
                                    ];
                                }
                            }
                        }
                        return prev;
                    });
                } else if (data.type === 'file_created') {
                    // Treat as standalone entry (merged via simplified timeline)
                    setMessages(prev => [...prev, {
                        role: 'file_event',
                        created_at: new Date().toISOString(),
                        file: {
                            file_path: data.file_path,
                            file_name: data.file_name,
                            size: data.size,
                            mime_type: data.mime_type,
                        }
                    }]);
                    // Increment new files count
                    setNewFilesCount(prev => prev + 1);
                    setFileRefreshTrigger(prev => prev + 1);
                } else if (data.type === 'status') {
                    setIsProcessing(data.status === 'busy');
                    if (data.content !== undefined) setStatusContent(data.content);
                } else if (data.type === 'hitl_request') {
                    // Directly populate from WS event (avoids race with /api/hitl fetch)
                    setHitlRequests(prev => {
                        if (prev.some(r => r.hitl_id === data.hitl_id)) return prev;
                        return [...prev, {
                            hitl_id: data.hitl_id,
                            session_id: data.session_id || sessionId,
                            tool_call_id: data.tool_call_id || '',
                            status: 'pending',
                            prompt: data.prompt,
                            hitl_type: data.hitl_type,
                            options: data.options || [],
                            context: data.context || '',
                            tool_name: data.tool_name,
                            tool_args: data.tool_args,
                            tool_permission_options: data.tool_permission_options || [],
                            request: {
                                type: data.hitl_type,
                                prompt: data.prompt,
                                options: data.options || [],
                                context: data.context || '',
                                tool_name: data.tool_name,
                                tool_args: data.tool_args,
                                tool_permission_options: data.tool_permission_options || [],
                            },
                        }];
                    });
                    // Agent is paused for HITL — stop processing indicator
                    setIsProcessing(false);
                } else if (data.type === 'hitl_resolved') {
                    // Remove resolved item and refresh from server
                    setHitlRequests(prev => prev.filter(r => r.hitl_id !== data.hitl_id));
                    fetch('/api/hitl')
                        .then(res => res.json())
                        .then(data => setHitlRequests(data));
                    fetchMessages(sessionId);
                } else if (data.type === 'token_usage') {
                    setLiveTokenCalls(prev => [...prev, {
                        model_id: data.model_id,
                        input_tokens: data.input_tokens,
                        output_tokens: data.output_tokens,
                    }]);
                    setTokenUsage(prev => prev + data.input_tokens + data.output_tokens);
                } else if (data.type === 'user_message_echo') {
                    // From another client on the same session — append user msg
                    if (data.client_id !== clientIdRef.current) {
                        setMessages(prev => [...prev, {
                            role: 'user',
                            content: data.content,
                            created_at: data.created_at || new Date().toISOString()
                        }]);
                    }
                }
            } catch (e) {
                console.log("WS Received non-json:", event.data);
            }
        };

        ws.onclose = (event) => {
            setIsConnected(false);
            setIsConnecting(false);

            // Auto-reconnect if not closed normally and session still active
            if (!event.wasClean && selectedSession?.session_id) {
                console.log("WS connection lost, attempting to reconnect in 3s...");
                setTimeout(() => {
                    if (selectedSession?.session_id) {
                        setReconnectTrigger(prev => prev + 1);
                    }
                }, 3000);
            }
        };

        ws.onerror = (e) => {
            console.error("WS Error:", e);
            setIsConnected(false);
            setIsConnecting(false);
        };

        wsRef.current = ws;

        return () => {
            ws.close();
        };
    }, [selectedSession?.session_id, reconnectTrigger]);

    const pendingSessionIds = new Set(
        hitlRequests
            .filter(r => {
                const sid = (r.origin_session_id || r.session_id);
                const session = sessions.find(s => s.session_id === sid);
                return session ? session.status === 'waiting_for_human' : true;
            })
            .map(r => (r.origin_session_id || r.session_id))
    );
    const currentHitlRequest = selectedSession
        ? hitlRequests.find(r => (r.origin_session_id || r.session_id) === selectedSession.session_id && r.status === 'pending')
        : null;
    const currentHitlPayload = currentHitlRequest ? (typeof currentHitlRequest.request === 'string' ? JSON.parse(currentHitlRequest.request) : currentHitlRequest.request) : null;

    // Any pending HITL request means chat input should resolve it (not send a new user_message)
    const isWaitingForInput = !!currentHitlRequest;

    const selectedSessionIdRef = useRef(selectedSession?.session_id);
    selectedSessionIdRef.current = selectedSession?.session_id;

    const handleHitlResolve = useCallback(async (hitlId, resolution) => {
        setIsProcessing(true);
        try {
            await fetch(`/api/hitl/${hitlId}/resolve`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(resolution)
            });
            setHitlRequests(prev => prev.filter(r => r.hitl_id !== hitlId));
            // Refetch messages and sessions to reflect resolved state
            if (selectedSessionIdRef.current) {
                fetchMessages(selectedSessionIdRef.current);
            }
            fetchSessions();
        } catch (error) {
            console.error('Failed to resolve HITL:', error);
        } finally {
            setIsProcessing(false);
        }
    }, []);

    // Relaxed isAgentOnline: if availableAgents is empty, assume online (avoids flicker/stuck during load)
    const isAgentOnline = (availableAgents.length === 0 && !loadingAgents) ||
        selectedSession?.agent_uuid?.startsWith('builtin_') ||
        availableAgents.some(a =>
            (a?.uuid && a.uuid === selectedSession?.agent_uuid) ||
            (a?.agent_name && a.agent_name.toLowerCase() === (selectedSession?.agent_name || '').toLowerCase())
        );

    const isNearBottom = () => {
        const el = scrollRef.current;
        if (!el) return true;
        return el.scrollHeight - el.scrollTop - el.clientHeight < 150;
    };

    const prevMsgCountRef = useRef(0);
    useEffect(() => {
        const prevCount = prevMsgCountRef.current;
        const curCount = messages.length;
        prevMsgCountRef.current = curCount;

        // Always scroll on first load or when new messages are appended
        if (prevCount === 0 || curCount > prevCount) {
            scrollToBottom();
        } else if (isNearBottom()) {
            // Only scroll on replace/re-render if user was already near bottom
            scrollToBottom();
        }
    }, [messages, isProcessing]);

    // Poll for files while the session is running
    useEffect(() => {
        if (!isProcessing || !selectedSession?.session_id) return;
        const interval = setInterval(() => {
            setFileRefreshTrigger(prev => prev + 1);
        }, 5000);
        return () => clearInterval(interval);
    }, [isProcessing, selectedSession?.session_id]);

    const scrollToBottom = () => {
        requestAnimationFrame(() => {
            if (scrollRef.current) {
                scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
            }
        });
    };

    const fetchSessions = () => {
        fetch('/api/sessions')
            .then(res => res.json())
            .then(data => {
                console.log(`[debug] Loaded ${data.length} sessions.`);
                setSessions(data);
            })
            .catch(err => console.error('Failed to fetch sessions:', err));
    };
    const fetchAgents = () => {
        setLoadingAgents(true);
        fetch('/api/agents')
            .then(res => res.json())
            .then(data => {
                setAvailableAgents(data);
                setLoadingAgents(false);
            })
            .catch(err => {
                console.error('Failed to fetch agents:', err);
                setLoadingAgents(false);
            });
    };

    const fetchMessages = (sid) => {
        if (!sid) return;

        const guessMime = (name) => {
            const ext = name.split('.').pop().toLowerCase();
            const map = {
                'mp4': 'video/mp4', 'mov': 'video/quicktime',
                'mp3': 'audio/mpeg', 'wav': 'audio/wav',
                'pdf': 'application/pdf', 'md': 'text/markdown',
                'html': 'text/html', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'ppt': 'application/vnd.ms-powerpoint', 'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                'mermaid': 'text/x-mermaid', 'mmd': 'text/x-mermaid',
                'excalidraw': 'application/json',
                'mindmap': 'application/json'
            };
            return map[ext] || 'application/octet-stream';
        };

        Promise.all([
            fetch(`/api/sessions/${sid}`).then(res => res.ok ? res.json() : { messages: [] }),
            fetch(`/api/sessions/${sid}/files`).then(res => res.ok ? res.json() : { files: [] })
        ]).then(([sessionData, fileData]) => {
            const baseMessages = sessionData.messages || [];
            const files = fileData.files || [];

            // 1. Create message entries for files and directories
            const fileEvents = files
                .map(f => ({
                    role: 'file_event',
                    created_at: f.modified_at,
                    file: {
                        file_path: f.name,
                        file_name: f.name,
                        size: f.size,
                        mime_type: f.type === 'directory' ? 'inode/directory' : guessMime(f.name)
                    }
                }));

            // 2. Merge and sort
            const merged = [...baseMessages, ...fileEvents];
            merged.sort((a, b) => {
                const timeA = new Date(a.created_at || a.timestamp || 0).getTime();
                const timeB = new Date(b.created_at || b.timestamp || 0).getTime();
                return timeA - timeB;
            });

            setMessages(merged);

            // Update session meta
            setSelectedSession(prev => ({
                ...sessionData,
                agent_uuid: sessionData.agent_uuid ?? prev?.agent_uuid,
            }));

            // Calculate tokens
            let sum = 0;
            const md = sessionData.metadata || {};
            const allCalls = [...(md.own_calls || []), ...(md.children_calls || [])];
            for (const call of allCalls) {
                sum += (call.input_tokens || 0) + (call.output_tokens || 0);
            }
            setTokenUsage(sum);

            setIsProcessing(sessionData.status === 'running');
            setStatusContent(sessionData.status === 'running' ? 'Thinking...' : '');
        }).catch(err => {
            console.warn(`[debug] fetchMessages failed for ${sid}:`, err);
        });
    };

    // connectWS is removed as it's now internal to the useEffect

    const sendMessage = async (inputVal) => {
        if (!inputVal?.trim() || !selectedSession) return;
        const currentInput = inputVal.trim();

        if (isWaitingForInput && currentHitlRequest) {
            setIsProcessing(true);
            setStatusContent('Submitting...');
            await handleHitlResolve(currentHitlRequest.hitl_id, {
                decision: currentInput,
                comment: ''
            });
            setIsProcessing(false);
            setStatusContent('');
            return;
        }

        const userMsg = { role: 'user', content: currentInput, timestamp: Date.now() };

        if (selectedSession.isNew) {
            setIsProcessing(true);
            setStatusContent('Thinking...');
            // Immediately append user message for responsiveness
            setMessages(prev => [...prev, userMsg]);

            try {
                const res = await fetch('/api/sessions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        agent_name: selectedSession.agent_uuid ? null : selectedSession.agent_name,
                        agent_uuid: selectedSession.agent_uuid,
                        user_input: currentInput
                    })
                });
                const data = await res.json();
                if (res.ok && data.session_id) {
                    // Navigate immediately to the new session
                    const newSessionStub = {
                        ...data,
                        agent_name: selectedSession.agent_name,
                        agent_uuid: selectedSession.agent_uuid,
                        messages: [...messages, userMsg],
                        metadata: selectedSession.metadata,
                        status: 'running',
                        created_at: new Date().toISOString(),
                        updated_at: new Date().toISOString(),
                        children: []
                    };

                    // Update local states BEFORE navigating to ensure the component 
                    // finds the session in the list immediately on re-render.
                    setSessions(prev => [newSessionStub, ...prev]);
                    setSelectedSession(newSessionStub);

                    navigate(`/sessions/${data.session_id}`, { replace: true });
                    // Removed the redundant fetchMessages call here as navigation 
                    // triggers the useEffect which already calls fetchMessages.

                } else {
                    console.error('Failed to create session:', data);
                    setMessages(prev => prev.filter(m => m !== userMsg)); // Remove optimistic message on error
                    setIsProcessing(false);
                    setStatusContent('');
                    alert(`Failed to start chat: ${data.detail || JSON.stringify(data)}`);
                }
            } catch (e) {
                console.error('Network error starting chat:', e);
                setMessages(prev => prev.filter(m => m !== userMsg));
                setIsProcessing(false);
                setStatusContent('');
                alert(`Failed to start chat: Network error or server unreachable. (${e.message})`);
            }
            return;
        }

        if (!isConnected) return;

        setMessages(prev => [...prev, userMsg]);
        setIsProcessing(true);
        setStatusContent('Thinking...');
        wsRef.current.send(JSON.stringify({ type: 'user_message', content: currentInput, client_id: clientIdRef.current }));
    };

    const stopSession = async () => {
        if (!selectedSession?.session_id) return;
        try {
            await fetch(`/api/sessions/${selectedSession.session_id}/stop`, { method: 'POST' });
        } catch (error) {
            console.error('Failed to stop session:', error);
        }
    };

    const resumeSession = async () => {
        if (!selectedSession?.session_id) return;
        setIsProcessing(true);
        setStatusContent('Resuming...');
        try {
            const res = await fetch(`/api/sessions/${selectedSession.session_id}/resume`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_input: "" })
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to resume session');
            }
            // Wait for WS events to handle the rest
        } catch (error) {
            console.error('Failed to resume session:', error);
            alert(`Failed to resume: ${error.message}`);
            setIsProcessing(false);
            setStatusContent('');
        }
    };

    const [sessionToDelete, setSessionToDelete] = useState(null);

    const handleDeleteClick = (e, session) => {
        e.stopPropagation();
        setSessionToDelete(session);
    };

    const confirmDelete = () => {
        if (!sessionToDelete) return;
        const sessionId = sessionToDelete.session_id;

        console.log(`Deleting session: ${sessionId}`);
        fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' })
            .then(res => {
                if (res.ok) {
                    console.log(`Session ${sessionId} deleted successfully.`);
                    const remaining = sessions.filter(s => s.session_id !== sessionId);
                    setSessions(remaining);
                    if (selectedSession?.session_id === sessionId) {
                        setSelectedSession(null);
                        setMessages([]);
                        if (remaining.length > 0) handleSelectSession(remaining[0]);
                    }
                } else {
                    console.error(`Failed to delete session ${sessionId}: ${res.status} ${res.statusText}`);
                    alert(`Failed to delete session: ${res.statusText}`);
                }
            })
            .catch(err => {
                console.error("Error deleting session:", err);
                alert("Error deleting session. Check console.");
            })
            .finally(() => setSessionToDelete(null));
    };

    const formatDate = (dateStr) => {
        const date = new Date(dateStr);
        return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    };

    // Stable greeting message object — only changes when selectedSession changes
    const greetingMessage = useMemo(() => {
        if (!selectedSession) return null;
        const agentCreatorGreeting = `Welcome to **Agent Architect**! I'm here to help you bring your AI vision to life.\n\nWhat kind of agent would you like to build? You can describe a role, a set of duties, or a specific workflow.\n\n![Agent Workflow](/agent_workflow_v3.png)`;
        const skillCreatorGreeting = `I am the **Skill Forge**, ready to implement custom logic for your agents.\n\nTell me about the capability you want to create. What input should it take, and what should it do?\n\n![Skill Workflow](/agent_workflow_v3.png)`;
        const greetings = {
            'Agent Creator': agentCreatorGreeting,
            'Agent Architect': agentCreatorGreeting,
            'Skill Creator': skillCreatorGreeting,
            'Skill Forge': skillCreatorGreeting,
        };
        const greeting = greetings[selectedSession.agent_name]
            || (selectedSession.agent_name ? `Hello! I am **${selectedSession.agent_name}**. How can I help you today?` : null);
        if (!greeting) return null;
        return {
            role: 'assistant',
            content: greeting,
            timestamp: selectedSession.created_at ? new Date(selectedSession.created_at).getTime() - 1000 : 0,
            _isFakeGreeting: true,
        };
    }, [selectedSession?.session_id, selectedSession?.agent_name, selectedSession?.created_at]);

    // Helper to merge assistant tool calls with subsequent tool outputs for rendering
    const renderMessages = useMemo(() => {
        const rendered = [];

        if (greetingMessage) rendered.push(greetingMessage);

        let i = 0;
        while (i < messages.length) {
            const msg = messages[i];

            // Check if this is an assistant message with tool_calls
            if (msg.role === 'assistant' && msg.tool_calls && msg.tool_calls.length > 0) {
                const tools = [];
                const filesInTurn = [];
                let j = i + 1;

                // Collect ALL tool results and file events until the turn ends
                // A turn ends when we hit a user message, another assistant message, or end of list
                while (j < messages.length && (messages[j].role === 'tool' || messages[j].role === 'file_event')) {
                    if (messages[j].role === 'tool') {
                        tools.push(messages[j]);
                    } else if (messages[j].role === 'file_event') {
                        filesInTurn.push(messages[j]);
                    }
                    j++;
                }

                // Add assistant message with its combined tool outputs
                rendered.push({ ...msg, relatedOutputs: tools });

                // Place all files created during this turn immediately after the assistant message
                if (filesInTurn.length > 0) {
                    rendered.push(...filesInTurn);
                }

                i = j;
            } else {
                rendered.push(msg);
                i++;
            }
        }
        return rendered;
    }, [greetingMessage, messages]);


    return (
        <div style={{ display: 'flex', height: '100%', background: '#f9fafb', overflow: 'hidden' }}>
            <SessionSidebar
                sessions={sessions}
                selectedSession={selectedSession}
                onSelectSession={handleSelectSession}
                onDeleteSession={handleDeleteClick}
                pendingSessionIds={pendingSessionIds}
                hitlRequests={hitlRequests}
                onOpenHitlModal={() => setIsHitlModalOpen(true)}
            />

            {/* 2. Main Chat Area */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, background: 'white', position: 'relative' }}>
                {selectedSession ? (
                    <>
                        {/* Header */}
                        <div style={{ height: '60px', flexShrink: 0, background: 'white', borderBottom: '1px solid var(--border)', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                                <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <h3 style={{ fontSize: '15px', color: '#111827', fontWeight: 700, margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {selectedSession.agent_name}
                                        </h3>
                                        {selectedSession.isNew && (
                                            <span style={{ fontSize: '10px', background: '#eff6ff', color: '#3b82f6', padding: '1px 6px', borderRadius: '4px', fontWeight: 600 }}>New Chat</span>
                                        )}
                                    </div>
                                    <div style={{ fontSize: '11px', color: '#6b7280', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {selectedSession.metadata?.title || (selectedSession.isNew ? 'Drafting first message...' : 'Untitled Session')}
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Messages List */}
                        <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px', minWidth: 0 }} ref={scrollRef}>
                            {/* System Prompt (Native details for stability) */}
                            {selectedSession.metadata?.system_prompt && String(selectedSession.metadata.system_prompt).trim() !== '' ? (
                                <div className={`system-prompt-details ${showSystemPrompt ? 'is-open' : ''}`}>
                                    <div
                                        className="system-prompt-summary"
                                        onClick={() => setShowSystemPrompt(!showSystemPrompt)}
                                    >
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <div style={{ padding: '4px', borderRadius: '6px', background: '#f1f5f9', color: '#64748b', display: 'flex' }}>
                                                    <Settings size={14} />
                                                </div>
                                                <span style={{ fontWeight: 600 }}>System Prompt</span>
                                            </div>
                                            <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 400 }}>
                                                {showSystemPrompt ? 'Click to collapse' : 'Click to expand'}
                                            </span>
                                        </div>
                                    </div>
                                    {showSystemPrompt && (
                                        <div className="system-prompt-content" key="sp-content">
                                            <ReactMarkdown
                                                remarkPlugins={[remarkGfm]}
                                                components={{
                                                    table: ({ node, ...props }) => <table style={{ borderCollapse: 'collapse', width: '100%', marginBottom: '16px', fontSize: '12px' }} {...props} />,
                                                    th: ({ node, ...props }) => <th style={{ border: '1px solid #e5e7eb', padding: '6px 10px', background: '#f9fafb', fontWeight: 600, textAlign: 'left' }} {...props} />,
                                                    td: ({ node, ...props }) => <td style={{ border: '1px solid #e5e7eb', padding: '6px 10px' }} {...props} />,
                                                    p: ({ node, ...props }) => <p style={{ margin: '0 0 4px 0' }} {...props} />,
                                                    pre: ({ node, ...props }) => <pre style={{ background: '#f3f4f6', padding: '8px', borderRadius: '4px', overflowX: 'auto', maxWidth: '100%' }} {...props} />,
                                                    code: ({ node, inline, ...props }) => <code style={{ background: inline ? '#f3f4f6' : 'transparent', padding: inline ? '2px 4px' : '0', borderRadius: '2px', wordBreak: 'break-all', whiteSpace: 'pre-wrap' }} {...props} />
                                                }}
                                            >
                                                {String(selectedSession.metadata.system_prompt)}
                                            </ReactMarkdown>
                                        </div>
                                    )}
                                </div>
                            ) : (
                                <div className="system-prompt-details">
                                    <div className="system-prompt-summary">
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', opacity: 0.6, width: '100%' }}>
                                            <div style={{ padding: '4px', borderRadius: '6px', background: '#f1f5f9', color: '#64748b', display: 'flex' }}>
                                                <Settings size={14} />
                                            </div>
                                            <span>System prompt is empty</span>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {renderMessages.map((m, idx) => (
                                <MessageItem
                                    key={idx}
                                    message={m}
                                    agentName={selectedSession.agent_name}
                                    hitlRequests={[...hitlRequests, ...(selectedSession?.hitl_requests || [])]}
                                    onResolve={handleHitlResolve}
                                    sessionId={selectedSession.session_id}
                                    sessionStatus={selectedSession.status}
                                    onPreviewFile={setPreviewFile}
                                />
                            ))}

                            {/* Inline tool permission HITL cards */}
                            {hitlRequests
                                .filter(r => (r.origin_session_id || r.session_id) === selectedSession.session_id && r.status === 'pending' && (r.hitl_type === 'tool_permission' || r.request?.type === 'tool_permission'))
                                .map(r => (
                                    <div key={r.hitl_id} style={{ display: 'flex', gap: '12px', padding: '8px 0' }}>
                                        <div style={{ width: '28px', height: '28px', borderRadius: '6px', background: '#eff6ff', color: '#3b82f6', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontSize: '14px', marginTop: '0px', boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
                                            <Bot size={16} />
                                        </div>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <HitlHistoryCard
                                                args={{
                                                    prompt: r.request?.prompt || r.prompt,
                                                    type: 'tool_permission',
                                                    options: r.request?.options || r.options || [],
                                                    context: r.request?.context || r.context || '',
                                                    hitl_id: r.hitl_id,
                                                    tool_name: r.request?.tool_name || r.tool_name,
                                                    tool_args: r.request?.tool_args || r.tool_args,
                                                    tool_permission_options: r.request?.tool_permission_options || r.tool_permission_options || [],
                                                }}
                                                output={null}
                                                hitlRequests={hitlRequests}
                                                onResolve={handleHitlResolve}
                                                sessionId={selectedSession.session_id}
                                                sessionStatus={selectedSession.status}
                                                toolCallId={r.tool_call_id}
                                            />
                                        </div>
                                    </div>
                                ))
                            }
                        </div>

                        {/* Input Area */}
                        <ChatInput
                            selectedSession={selectedSession}
                            isAgentOnline={isAgentOnline}
                            isWaitingForInput={isWaitingForInput}
                            isProcessing={isProcessing}
                            isConnected={isConnected}
                            isConnecting={isConnecting}
                            currentHitlPayload={currentHitlPayload}
                            onSendMessage={sendMessage}
                            onStop={stopSession}
                            onRetry={resumeSession}
                            statusContent={statusContent}
                            CREATOR_SUGGESTIONS={CREATOR_SUGGESTIONS}
                            renderMessagesCount={renderMessages.length}
                        />
                    </>
                ) : (
                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: '16px', color: '#9ca3af' }}>
                        <MessageSquare size={48} style={{ opacity: 0.2 }} />
                        <div style={{ fontSize: '14px' }}>Select a session to start chatting</div>
                    </div>
                )}
            </div>

            {/* 3. Right Details Panel */}
            <SessionDetails
                selectedSession={selectedSession}
                messages={messages}
                availableAgents={availableAgents}
                config={config}
                tokenUsage={tokenUsage}
                liveTokenCalls={liveTokenCalls}
                newFilesCount={newFilesCount}
                setNewFilesCount={setNewFilesCount}
                fileRefreshTrigger={fileRefreshTrigger}
                onPreviewFile={setPreviewFile}
            />
            {/* Delete Modal */}
            {/* Delete Modal */}
            <Modal
                isOpen={!!sessionToDelete}
                onClose={() => setSessionToDelete(null)}
                title="Delete Session"
                footer={
                    <>
                        <button
                            onClick={() => setSessionToDelete(null)}
                            style={{
                                padding: '8px 16px',
                                borderRadius: '6px',
                                border: '1px solid #e5e7eb',
                                background: 'white',
                                color: '#374151',
                                cursor: 'pointer',
                                fontWeight: 500
                            }}
                        >
                            Cancel
                        </button>
                        <button
                            onClick={confirmDelete}
                            style={{
                                padding: '8px 16px',
                                borderRadius: '6px',
                                border: 'none',
                                background: '#ef4444',
                                color: 'white',
                                cursor: 'pointer',
                                fontWeight: 500
                            }}
                        >
                            Delete
                        </button>
                    </>
                }
            >
                Are you sure you want to delete the session for agent <strong>{sessionToDelete?.agent_name}</strong>? This action cannot be undone.
            </Modal>

            {/* HITL Requests Modal */}
            <Modal
                isOpen={isHitlModalOpen}
                onClose={() => setIsHitlModalOpen(false)}
                title="HITL (Approval/Decision/Input)"
                width="700px"
                footer={
                    <button
                        onClick={() => setIsHitlModalOpen(false)}
                        style={{
                            padding: '8px 16px',
                            borderRadius: '6px',
                            border: '1px solid #e5e7eb',
                            background: 'white',
                            color: '#374151',
                            cursor: 'pointer',
                            fontWeight: 500
                        }}
                    >
                        Close
                    </button>
                }
            >
                <div style={{ maxHeight: '60vh', overflowY: 'auto', paddingRight: '4px' }}>
                    <HitlPanel
                        requests={hitlRequests}
                        onResolve={async (id, res) => {
                            await handleHitlResolve(id, res);
                            if (hitlRequests.length <= 1) setIsHitlModalOpen(false);
                        }}
                    />
                </div>
            </Modal>
            {
                previewFile && selectedSession && (
                    <FilePreviewModal
                        file={previewFile}
                        sessionId={selectedSession.session_id}
                        onClose={() => setPreviewFile(null)}
                    />
                )
            }
        </div >
    );
}

// Reusable Modal Component (Inline for simplicity or import if shared)
const Modal = ({ isOpen, onClose, title, children, footer, width = '400px' }) => {
    if (!isOpen) return null;
    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
        }} onClick={onClose}>
            <div style={{
                background: 'white', borderRadius: '12px', width: width, maxWidth: '95%',
                padding: '24px', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)'
            }} onClick={e => e.stopPropagation()}>
                <div style={{ fontSize: '18px', fontWeight: 600, marginBottom: '16px', color: '#1f2937' }}>{title}</div>
                <div style={{ marginBottom: '24px', color: '#4b5563', fontSize: '14px', lineHeight: '1.5' }}>{children}</div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>{footer}</div>
            </div>
        </div>
    );
};




