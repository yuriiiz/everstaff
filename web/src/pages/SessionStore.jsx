import { useState, useEffect, useRef, memo, useMemo, useCallback } from 'react';
import { useSearchParams, useParams, useNavigate } from 'react-router-dom';
import { MessageSquare, User, Trash2, Send, ChevronRight, ChevronDown, Terminal, Cpu, Bot, UserCheck, Check, Search, X, Sparkles, Zap, Filter, Folder, Square } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { HitlPanel } from './HitlComponents';
import FileCard from '../components/FileCard';
import FilePreviewModal from '../components/FilePreviewModal';
import FileBrowser from '../components/FileBrowser';

import { ChatInput, CREATOR_SUGGESTIONS } from '../components/ChatInput';
import { MessageItem } from '../components/ChatMessages';
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
                        return [...prev, { role: 'assistant', content: data.content, streaming: true, timestamp: Date.now() }];
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
                        return [...prev, { role: 'assistant', thinking: data.content, streaming: true, timestamp: Date.now(), content: '' }];
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
                        return [...prev, { role: 'assistant', content: '', streaming: true, tool_calls: [pendingTC], timestamp: Date.now() }];
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
                    setMessages(prev => {
                        for (let i = prev.length - 1; i >= 0; i--) {
                            if (prev[i].role === 'assistant') {
                                const artifacts = [...(prev[i].fileArtifacts || []), {
                                    file_path: data.file_path,
                                    file_name: data.file_name,
                                    size: data.size,
                                    mime_type: data.mime_type,
                                }];
                                return [
                                    ...prev.slice(0, i),
                                    { ...prev[i], fileArtifacts: artifacts },
                                    ...prev.slice(i + 1),
                                ];
                            }
                        }
                        return prev;
                    });
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
                            timestamp: Date.now()
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
        fetch(`/api/sessions/${sid}`)
            .then(res => {
                if (!res.ok) throw new Error(`HTTP error ${res.status}`);
                return res.json();
            })
            .then(data => {
                // If the backend has no messages yet (just created), 
                // but we already have optimistic messages locally, don't wipe them.
                if ((!data.messages || data.messages.length === 0) && messages.length > 0 && selectedSession?.session_id === sid) {
                    console.log(`[debug] Keeping local optimistic messages for ${sid}`);
                } else {
                    setMessages(data.messages || []);
                }

                // Preserve agent_uuid from previous state if backend hasn't written it yet
                setSelectedSession(prev => ({
                    ...data,
                    agent_uuid: data.agent_uuid ?? prev?.agent_uuid,
                }));

                // Manually calculate total token usage
                let sum = 0;
                const md = data.metadata || {};
                const allCalls = [...(md.own_calls || []), ...(md.children_calls || [])];
                for (const call of allCalls) {
                    sum += (call.input_tokens || 0) + (call.output_tokens || 0);
                }
                setTokenUsage(sum);

                setIsProcessing(data.status === 'running');
                setStatusContent(data.status === 'running' ? 'Thinking...' : '');
                setShowSystemPrompt(false);

                // Fetch workspace files and attach to last assistant message
                fetch(`/api/sessions/${sid}/files`)
                    .then(r => r.ok ? r.json() : { files: [] })
                    .then(fileData => {
                        if (fileData.files && fileData.files.length > 0) {
                            const artifacts = fileData.files
                                .filter(f => f.type === 'file')
                                .map(f => ({
                                    file_path: f.name,
                                    file_name: f.name,
                                    size: f.size,
                                    mime_type: guessMimeClient(f.name),
                                }));
                            if (artifacts.length > 0) {
                                setMessages(prev => {
                                    for (let i = prev.length - 1; i >= 0; i--) {
                                        if (prev[i].role === 'assistant') {
                                            return [
                                                ...prev.slice(0, i),
                                                { ...prev[i], fileArtifacts: artifacts },
                                                ...prev.slice(i + 1),
                                            ];
                                        }
                                    }
                                    return prev;
                                });
                            }
                        }
                    })
                    .catch(() => { });
            })
            .catch(err => {
                console.warn(`[debug] fetchMessages failed for ${sid}: ${err.message}. Preserving state.`);
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
                // Look ahead for corresponding tool outputs
                const tools = [...msg.tool_calls];
                const outputs = [];
                let j = i + 1;
                while (j < messages.length && messages[j].role === 'tool') {
                    outputs.push(messages[j]);
                    j++;
                }
                rendered.push({ ...msg, relatedOutputs: outputs });
                i = j; // Skip the tool outputs we just consumed
            } else if (msg.role === 'tool') {
                // Orphaned tool output (shouldn't really happen with this logic, but handle it)
                rendered.push(msg);
                i++;
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
                            {/* System Prompt (Folded) */}
                            {selectedSession.metadata?.system_prompt && (
                                <div className="system-prompt-wrapper">
                                    <button
                                        onClick={() => setShowSystemPrompt(!showSystemPrompt)}
                                        className="system-prompt-header"
                                    >
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <Terminal size={14} />
                                            <span>System Prompt</span>
                                        </div>
                                        <ChevronDown
                                            size={14}
                                            style={{
                                                transition: 'transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
                                                transform: showSystemPrompt ? 'rotate(180deg)' : 'rotate(0deg)'
                                            }}
                                        />
                                    </button>
                                    <div className={`system-prompt-anim-container ${showSystemPrompt ? 'open' : ''}`}>
                                        <div className="system-prompt-content-inner">
                                            <ReactMarkdown
                                                remarkPlugins={[remarkGfm]}
                                                components={{
                                                    table: ({ node, ...props }) => <table style={{ borderCollapse: 'collapse', width: '100%', marginBottom: '16px', fontSize: '12px' }} {...props} />,
                                                    th: ({ node, ...props }) => <th style={{ border: '1px solid #e5e7eb', padding: '6px 10px', background: '#f9fafb', fontWeight: 600, textAlign: 'left' }} {...props} />,
                                                    td: ({ node, ...props }) => <td style={{ border: '1px solid #e5e7eb', padding: '6px 10px' }} {...props} />,
                                                    p: ({ node, ...props }) => <p style={{ margin: '0 0 10px 0' }} {...props} />,
                                                    pre: ({ node, ...props }) => <pre style={{ background: '#f3f4f6', padding: '8px', borderRadius: '4px', overflowX: 'auto', maxWidth: '100%' }} {...props} />,
                                                    code: ({ node, inline, ...props }) => <code style={{ background: inline ? '#f3f4f6' : 'transparent', padding: inline ? '2px 4px' : '0', borderRadius: '2px', wordBreak: 'break-all', whiteSpace: 'pre-wrap' }} {...props} />
                                                }}
                                            >
                                                {selectedSession.metadata?.system_prompt}
                                            </ReactMarkdown>
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


const HitlHistoryCard = ({ args, output, hitlRequests, onResolve, sessionId, sessionStatus, toolCallId }) => {
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
            // Also check if one is a substring of another to handle minor formatting differences
            if (p1.includes(p2) || p2.includes(p1)) return true;
        }

        return false;
    });

    // 4. Fallback: If no direct match was found, but this session IS waiting for human AND 
    // there is exactly ONE pending request for this session, assume it's the one.
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
            // Check for legacy format
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
            // Priority for hitl_id: pendingRequest match > parsedArgs > live API fetch fallback
            let hitlIdToResolve = pendingRequest?.hitl_id || parsedArgs?.hitl_id;

            if (!hitlIdToResolve) {
                // Fallback: fetch the latest HITL list and try matching again
                try {
                    const res = await fetch('/api/hitl');
                    const freshRequests = await res.json();
                    const match = freshRequests.find(r =>
                        (r.origin_session_id || r.session_id) === sessionId && r.status === 'pending' &&
                        (!toolCallId || r.tool_call_id === toolCallId)
                    ) || freshRequests.find(r =>
                        (r.origin_session_id || r.session_id) === sessionId && r.status === 'pending'
                    );
                    hitlIdToResolve = match?.hitl_id;
                } catch (e) {
                    console.error("Fallback HITL fetch failed:", e);
                }
            }

            if (!hitlIdToResolve) {
                console.error("Could not determine hitl_id to resolve", { toolCallId, prompt });
                alert("Error: Could not identify the hitl_id for this request.");
                return;
            }

            await onResolve(hitlIdToResolve, {
                decision: decision,
                comment: comment,
                ...extraFields,
            });
        } catch (error) {
            console.error("Failed to resolve HITL:", error);
            alert("Failed to resolve: " + error.message);
        } finally {
            setIsSubmitting(false);
        }
    };



    return (
        <div style={{
            background: isPending ? '#ffffff' : (isExpired ? '#fff1f2' : '#f8fafc'),
            border: isPending ? '1px solid #3b82f6' : (isExpired ? '1px solid #fecdd3' : '1px solid #e2e8f0'),
            borderRadius: '12px',
            padding: '16px',
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            gap: '14px',
            marginTop: '8px',
            position: 'relative',
            boxShadow: isPending ? '0 4px 20px -5px rgba(59, 130, 246, 0.15)' : 'none',
            transition: 'all 0.3s ease'
        }}>
            {/* Header / Status */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    color: isPending ? '#2563eb' : (isExpired ? '#e11d48' : '#64748b')
                }}>
                    <UserCheck size={16} strokeWidth={2.5} />
                    <span style={{
                        fontSize: '11px',
                        fontWeight: 800,
                        textTransform: 'uppercase',
                        letterSpacing: '0.06em'
                    }}>
                        {isPending ? (type === 'tool_permission' ? 'Tool Permission Required' : 'Human Input Required') : (isExpired || output?.content === 'expired' ? 'Interaction Expired' : 'Interaction Resolved')}
                    </span>
                </div>
                {isPending && (
                    <div style={{
                        fontSize: '10px',
                        background: '#eff6ff',
                        color: '#3b82f6',
                        padding: '3px 10px',
                        borderRadius: '20px',
                        fontWeight: 700,
                        border: '1px solid #dbeafe'
                    }}>
                        Active
                    </div>
                )}
            </div>

            {/* Context Content */}
            {context && (
                <div style={{
                    fontSize: '13px',
                    color: '#475569',
                    background: isPending ? '#f1f5f9' : '#f8fafc',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    borderLeft: '3px solid #64748b',
                    whiteSpace: 'pre-wrap',
                    marginBottom: '-4px'
                }}>
                    {context}
                </div>
            )}

            {/* Tool Permission Prompt */}
            {type === 'tool_permission' && prompt && (
                <div style={{
                    fontSize: '13px',
                    color: '#1e293b',
                    lineHeight: '1.6',
                    background: isPending ? '#fffbeb' : '#f8fafc',
                    padding: '12px',
                    borderRadius: '8px',
                    border: isPending ? '1px solid #fde68a' : '1px solid #e2e8f0',
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                }}>
                    {prompt}
                </div>
            )}

            {/* Prompt Content */}
            {type !== 'notify' && type !== 'provide_input' && type !== 'tool_permission' && prompt && (
                <div style={{
                    fontSize: '14px',
                    color: '#1e293b',
                    fontWeight: 600,
                    lineHeight: '1.6',
                    background: isPending ? '#f8fafc' : 'transparent',
                    padding: isPending ? '12px' : '0',
                    borderRadius: '8px',
                    border: isPending ? '1px solid #f1f5f9' : 'none'
                }}>
                    {prompt}
                </div>
            )}

            {isPending ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                    {/* Interaction Types */}
                    {type === 'tool_permission' && (() => {
                        const structuredOpts = parsedArgs?.tool_permission_options
                            || pendingRequest?.tool_permission_options
                            || pendingRequest?.request?.tool_permission_options
                            || [];
                        const colorMap = {
                            'reject': '#ef4444',
                            'approve_once': '#10b981',
                            'approve_session_narrow': '#3b82f6',
                            'approve_session': '#3b82f6',
                            'approve_permanent_narrow': '#6366f1',
                            'approve_permanent': '#6366f1',
                        };
                        const buttons = structuredOpts.length > 0
                            ? structuredOpts.map(opt => ({
                                key: opt.id,
                                label: opt.label,
                                color: colorMap[opt.id] || '#3b82f6',
                                primary: opt.id === 'approve_once',
                                scope: opt.scope,
                                pattern: opt.pattern,
                            }))
                            : [
                                { key: 'approve_once', label: 'Allow Once', color: '#10b981', primary: true },
                                { key: 'approve_session', label: 'Allow for Session', color: '#3b82f6', primary: false },
                                { key: 'approve_permanent', label: 'Always Allow', color: '#6366f1', primary: false },
                                { key: 'reject', label: 'Reject', color: '#ef4444', primary: false },
                            ];
                        return (
                            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                {buttons.map(btn => (
                                    <button
                                        key={btn.key}
                                        disabled={isSubmitting}
                                        onClick={() => handleAction(btn.key, "", {
                                            grant_scope: btn.scope || undefined,
                                            permission_pattern: btn.pattern || undefined,
                                        })}
                                        style={{
                                            padding: '10px 16px',
                                            background: isSubmitting ? '#f8fafc' : btn.primary ? btn.color : '#ffffff',
                                            color: isSubmitting ? '#94a3b8' : btn.primary ? 'white' : btn.color,
                                            border: btn.primary ? 'none' : `1px solid ${btn.color}30`,
                                            borderRadius: '10px',
                                            fontSize: '13px',
                                            fontWeight: 700,
                                            cursor: isSubmitting ? 'default' : 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            gap: '8px',
                                            boxShadow: btn.primary && !isSubmitting ? `0 2px 4px ${btn.color}33` : 'none',
                                            transition: 'all 0.2s'
                                        }}
                                        onMouseEnter={e => { if (!isSubmitting) { e.currentTarget.style.opacity = '0.85'; } }}
                                        onMouseLeave={e => { if (!isSubmitting) { e.currentTarget.style.opacity = '1'; } }}
                                    >
                                        {isSubmitting ? (
                                            <div style={{ width: '14px', height: '14px', border: '2px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                                        ) : btn.key === 'reject' ? <X size={14} /> : <Check size={14} />}
                                        {isSubmitting ? '...' : btn.label}
                                    </button>
                                ))}
                            </div>
                        );
                    })()}

                    {type === 'approve_reject' && (
                        <div style={{ display: 'flex', gap: '10px' }}>
                            <button
                                disabled={isSubmitting}
                                onClick={() => handleAction('approved')}
                                style={{
                                    flex: 1,
                                    padding: '10px 16px',
                                    background: isSubmitting ? '#94a3b8' : '#10b981',
                                    color: 'white',
                                    border: 'none',
                                    borderRadius: '10px',
                                    fontSize: '13px',
                                    fontWeight: 700,
                                    cursor: isSubmitting ? 'default' : 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '8px',
                                    boxShadow: isSubmitting ? 'none' : '0 2px 4px rgba(16, 185, 129, 0.2)',
                                    transition: 'transform 0.2s, background 0.2s'
                                }}
                                onMouseEnter={e => { if (!isSubmitting) e.currentTarget.style.background = '#059669'; }}
                                onMouseLeave={e => { if (!isSubmitting) e.currentTarget.style.background = '#10b981'; }}
                            >
                                {isSubmitting ? (
                                    <div style={{ width: '16px', height: '16px', border: '2px solid rgba(255,255,255,0.3)', borderTopColor: 'white', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                                ) : <Check size={16} />}
                                {isSubmitting ? 'Processing...' : 'Approve'}
                            </button>
                            <button
                                disabled={isSubmitting}
                                onClick={() => handleAction('rejected')}
                                style={{
                                    flex: 1,
                                    padding: '10px 16px',
                                    background: isSubmitting ? '#f8fafc' : '#ffffff',
                                    color: isSubmitting ? '#94a3b8' : '#ef4444',
                                    border: '1px solid #fee2e2',
                                    borderRadius: '10px',
                                    fontSize: '13px',
                                    fontWeight: 700,
                                    cursor: isSubmitting ? 'default' : 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '8px',
                                    transition: 'all 0.2s'
                                }}
                                onMouseEnter={e => {
                                    if (!isSubmitting) {
                                        e.currentTarget.style.background = '#fef2f2';
                                        e.currentTarget.style.borderColor = '#ef4444';
                                    }
                                }}
                                onMouseLeave={e => {
                                    if (!isSubmitting) {
                                        e.currentTarget.style.background = '#ffffff';
                                        e.currentTarget.style.borderColor = '#fee2e2';
                                    }
                                }}
                            >
                                {isSubmitting ? (
                                    <div style={{ width: '16px', height: '16px', border: '2px solid rgba(239,68,68,0.2)', borderTopColor: '#ef4444', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                                ) : <X size={16} />}
                                {isSubmitting ? '...' : 'Reject'}
                            </button>
                        </div>
                    )}

                    {type === 'choose' && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            {optionsArray?.map(opt => (
                                <button
                                    key={opt}
                                    disabled={isSubmitting}
                                    onClick={() => handleAction(opt)}
                                    style={{
                                        padding: '10px 14px',
                                        background: isSubmitting ? '#f8fafc' : '#ffffff',
                                        border: '1px solid #e2e8f0',
                                        borderRadius: '10px',
                                        fontSize: '13px',
                                        fontWeight: 600,
                                        color: isSubmitting ? '#94a3b8' : '#334155',
                                        cursor: isSubmitting ? 'default' : 'pointer',
                                        textAlign: 'left',
                                        transition: 'all 0.2s',
                                        boxShadow: '0 1px 2px rgba(0,0,0,0.02)',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '10px'
                                    }}
                                    onMouseEnter={e => {
                                        if (!isSubmitting) {
                                            e.currentTarget.style.borderColor = '#3b82f6';
                                            e.currentTarget.style.background = '#eff6ff';
                                            e.currentTarget.style.color = '#1d4ed8';
                                        }
                                    }}
                                    onMouseLeave={e => {
                                        if (!isSubmitting) {
                                            e.currentTarget.style.borderColor = '#e2e8f0';
                                            e.currentTarget.style.background = '#ffffff';
                                            e.currentTarget.style.color = '#334155';
                                        }
                                    }}
                                >
                                    {isSubmitting && (
                                        <div style={{ width: '12px', height: '12px', border: '2px solid rgba(59,130,246,0.1)', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                                    )}
                                    {opt}
                                </button>
                            ))}
                        </div>
                    )}

                    {type === 'provide_input' && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', background: isPending ? '#f8fafc' : 'transparent', padding: isPending ? '14px' : '0', borderRadius: '12px', border: isPending ? '1px solid #e2e8f0' : 'none' }}>
                            {prompt && (
                                <div style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b', marginBottom: '4px' }}>
                                    {prompt}
                                </div>
                            )}
                            <textarea
                                value={userInput}
                                onChange={e => setUserInput(e.target.value)}
                                placeholder="Write your response or instructions..."
                                disabled={isSubmitting}
                                style={{
                                    width: '100%',
                                    minHeight: '100px',
                                    padding: '14px',
                                    borderRadius: '12px',
                                    border: '1px solid #e2e8f0',
                                    fontSize: '13.5px',
                                    resize: 'none',
                                    outline: 'none',
                                    background: '#ffffff',
                                    transition: 'all 0.2s',
                                    lineHeight: '1.5'
                                }}
                                onFocus={e => {
                                    e.currentTarget.style.borderColor = '#3b82f6';
                                    e.currentTarget.style.boxShadow = '0 0 0 3px rgba(59, 130, 246, 0.1)';
                                }}
                                onBlur={e => {
                                    e.currentTarget.style.borderColor = '#e2e8f0';
                                    e.currentTarget.style.boxShadow = 'none';
                                }}
                            />
                            <button
                                disabled={isSubmitting || !userInput.trim()}
                                onClick={() => handleAction(userInput)}
                                style={{
                                    padding: '12px 20px',
                                    background: isSubmitting || !userInput.trim() ? '#94a3b8' : '#111827',
                                    color: 'white',
                                    border: 'none',
                                    borderRadius: '10px',
                                    fontSize: '14px',
                                    fontWeight: 700,
                                    cursor: isSubmitting || !userInput.trim() ? 'default' : 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '8px',
                                    boxShadow: (isSubmitting || !userInput.trim()) ? 'none' : '0 4px 6px -1px rgba(0,0,0,0.1)',
                                    transition: 'all 0.2s'
                                }}
                                onMouseEnter={e => {
                                    if (!isSubmitting && userInput.trim()) e.currentTarget.style.background = '#000000';
                                }}
                                onMouseLeave={e => {
                                    if (!isSubmitting && userInput.trim()) e.currentTarget.style.background = '#111827';
                                }}
                            >
                                {isSubmitting ? (
                                    <div style={{ width: '16px', height: '16px', border: '2px solid rgba(255,255,255,0.3)', borderTopColor: 'white', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                                ) : <Send size={16} />}
                                {isSubmitting ? 'Submitting...' : 'Submit Resolution'}
                            </button>
                        </div>
                    )}

                    {type === 'notify' && (
                        <div style={{ display: 'flex' }}>
                            <button
                                disabled={isSubmitting}
                                onClick={() => handleAction('acknowledged')}
                                style={{
                                    width: '100%',
                                    padding: '10px 16px',
                                    background: isSubmitting ? '#94a3b8' : '#3b82f6',
                                    color: 'white',
                                    border: 'none',
                                    borderRadius: '10px',
                                    fontSize: '13px',
                                    fontWeight: 700,
                                    cursor: isSubmitting ? 'default' : 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '8px',
                                    transition: 'background 0.2s'
                                }}
                                onMouseEnter={e => { if (!isSubmitting) e.currentTarget.style.background = '#2563eb'; }}
                                onMouseLeave={e => { if (!isSubmitting) e.currentTarget.style.background = '#3b82f6'; }}
                            >
                                {isSubmitting ? (
                                    <div style={{ width: '16px', height: '16px', border: '2px solid rgba(255,255,255,0.3)', borderTopColor: 'white', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                                ) : <Check size={16} />}
                                {isSubmitting ? 'Confirming...' : 'Acknowledge'}
                            </button>
                        </div>
                    )}
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        <div style={{
                            padding: '3px 10px',
                            background: '#f1f5f9',
                            borderRadius: '12px',
                            fontSize: '10px',
                            color: '#475569',
                            fontWeight: 700,
                            border: '1px solid #e2e8f0',
                            textTransform: 'uppercase'
                        }}>
                            {type}
                        </div>
                    </div>

                    {resolution && (
                        <div style={{
                            marginTop: '4px',
                            padding: '14px',
                            background: '#ffffff',
                            borderRadius: '10px',
                            border: '1px solid #e2e8f0',
                            borderLeft: '4px solid #10b981',
                            boxShadow: '0 1px 2px rgba(0,0,0,0.03)'
                        }}>
                            <div style={{
                                fontSize: '10px',
                                color: '#94a3b8',
                                fontWeight: 800,
                                textTransform: 'uppercase',
                                marginBottom: '6px',
                                letterSpacing: '0.04em'
                            }}>
                                Decision Outcome
                            </div>
                            <div style={{
                                fontSize: '14px',
                                fontWeight: 700,
                                color: '#0f172a',
                                marginBottom: resolution.comment ? '8px' : '0'
                            }}>
                                {resolution.decision}
                            </div>
                            {resolution.comment && (
                                <div style={{
                                    fontSize: '13px',
                                    color: '#64748b',
                                    padding: '10px',
                                    background: '#f8fafc',
                                    borderRadius: '6px',
                                    fontStyle: 'italic',
                                    lineHeight: '1.5'
                                }}>
                                    "{resolution.comment}"
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};



