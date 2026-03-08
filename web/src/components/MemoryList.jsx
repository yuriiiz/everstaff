import React, { useState, useEffect } from 'react';
import { Search, Brain, Clock, User, Globe, Activity, Loader2 } from 'lucide-react';
import LoadingView from './LoadingView';

export default function MemoryList({ agentUuid = null }) {
    const [memories, setMemories] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [isSearching, setIsSearching] = useState(false);

    useEffect(() => {
        fetchMemories();
    }, [agentUuid]);

    const fetchMemories = async () => {
        setLoading(true);
        try {
            const url = agentUuid 
                ? `/api/agents/${agentUuid}/memories?limit=100`
                : '/api/memories?limit=100';
            const res = await fetch(url);
            if (res.ok) {
                const data = await res.json();
                setMemories(data.memories || []);
            }
        } catch (e) {
            console.error('Failed to fetch memories', e);
        } finally {
            setLoading(false);
        }
    };

    const handleSearch = async (e) => {
        e.preventDefault();
        if (!searchQuery.trim()) {
            fetchMemories();
            return;
        }

        setIsSearching(true);
        try {
            const url = agentUuid
                ? `/api/agents/${agentUuid}/memories/search?q=${encodeURIComponent(searchQuery)}&limit=50`
                : `/api/memories/search?q=${encodeURIComponent(searchQuery)}&limit=50`;
            const res = await fetch(url);
            if (res.ok) {
                const data = await res.json();
                setMemories(data.memories || []);
            }
        } catch (e) {
            console.error('Failed to search memories', e);
        } finally {
            setIsSearching(false);
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <div style={{ padding: agentUuid ? '0 0 16px 0' : '24px', flexShrink: 0 }}>
                <form onSubmit={handleSearch} style={{ display: 'flex', gap: '12px' }}>
                    <div style={{ position: 'relative', flex: 1 }}>
                        <Search size={18} color="#9ca3af" style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)' }} />
                        <input
                            type="text"
                            className="input-field"
                            placeholder="Semantic search memories..."
                            style={{ paddingLeft: '44px', width: '100%' }}
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>
                    <button type="submit" className="btn btn-primary" disabled={isSearching} style={{ width: '80px', display: 'flex', justifyContent: 'center' }}>
                        {isSearching ? <Loader2 size={16} className="animate-spin" /> : 'Search'}
                    </button>
                    {searchQuery && (
                        <button type="button" className="btn btn-secondary" onClick={() => { setSearchQuery(''); fetchMemories(); }}>
                            Clear
                        </button>
                    )}
                </form>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: agentUuid ? '0' : '0 24px 24px' }}>
                {loading ? (
                    <LoadingView message="Loading memories..." />
                ) : memories.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '40px', color: '#6b7280' }}>
                        <Brain size={48} color="#d1d5db" style={{ margin: '0 auto 16px' }} />
                        <p style={{ fontSize: '16px', fontWeight: 500 }}>No memories found</p>
                        <p style={{ fontSize: '14px', marginTop: '8px' }}>As agents interact, they will build up memories here.</p>
                    </div>
                ) : (
                    <div style={{ display: 'grid', gap: agentUuid ? '8px' : '16px' }}>
                        {memories.map((m) => {
                            const isShared = m.user_id === 'default';
                            return (
                                <div key={m.id} style={{
                                    background: 'white',
                                    border: '1px solid #e5e7eb',
                                    borderRadius: agentUuid ? '8px' : '12px',
                                    padding: agentUuid ? '12px 16px' : '16px 20px',
                                    boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: agentUuid ? '8px' : '12px'
                                }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                        <div style={{ fontSize: agentUuid ? '13px' : '14px', color: '#111827', lineHeight: '1.5', flex: 1, whiteSpace: 'pre-wrap' }}>
                                            {m.memory}
                                        </div>
                                        {m.score !== undefined && (
                                            <div style={{
                                                background: '#f0fdf4',
                                                color: '#166534',
                                                padding: '4px 8px',
                                                borderRadius: '6px',
                                                fontSize: '12px',
                                                fontWeight: 600,
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '4px',
                                                marginLeft: '16px'
                                            }}>
                                                <Activity size={12} />
                                                {(m.score * 100).toFixed(0)}%
                                            </div>
                                        )}
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap', borderTop: '1px solid #f3f4f6', paddingTop: agentUuid ? '8px' : '12px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: '#6b7280' }}>
                                            <Clock size={12} />
                                            <span>Created {new Date(m.created_at || m.updated_at).toLocaleString()}</span>
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: isShared ? '#8b5cf6' : '#3b82f6', background: isShared ? '#f5f3ff' : '#eff6ff', padding: '2px 8px', borderRadius: '4px' }}>
                                            {isShared ? <Globe size={12} /> : <User size={12} />}
                                            <span style={{ fontWeight: 500 }}>{isShared ? 'Shared Memory' : 'Personal Memory'}</span>
                                        </div>
                                        {!agentUuid && m.agent_id && (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#4b5563', background: '#f3f4f6', padding: '2px 8px', borderRadius: '4px' }}>
                                                <Brain size={12} />
                                                Agent: <span style={{ fontWeight: 500, userSelect: 'all' }}>{m.agent_id}</span>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}
