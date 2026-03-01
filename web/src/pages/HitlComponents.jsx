import { useState } from 'react';
import { UserCheck, MessageSquare, Check, X, AlertTriangle, ExternalLink, HelpCircle, List, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export const HitlPanel = ({ requests, onResolve }) => {
    if (!requests || requests.length === 0) return (
        <div style={{ textAlign: 'center', padding: '40px', color: '#94a3b8', fontSize: '14px' }}>
            No pending decisions.
        </div>
    );

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            width: '100%',
            background: 'white',
            borderRadius: '12px',
            border: '1px solid #e2e8f0',
            overflow: 'hidden'
        }}>
            <style>{`
                @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
                @keyframes fadeIn {
                    from { opacity: 0; transform: translateY(4px); }
                    to { opacity: 1; transform: translateY(0); }
                }
            `}</style>
            {requests.map((req, idx) => (
                <div key={req.hitl_id} style={{
                    borderBottom: idx < requests.length - 1 ? '1px solid #e2e8f0' : 'none',
                    animation: `fadeIn 0.3s ease-out ${idx * 0.05}s both`
                }}>
                    <HitlRequestCard request={req} onResolve={onResolve} />
                </div>
            ))}
        </div>
    );
};

const HitlRequestCard = ({ request, onResolve }) => {
    const [submittingAction, setSubmittingAction] = useState(null);
    const navigate = useNavigate();

    const payload = typeof request.request === 'string' ? JSON.parse(request.request) : (request.request || {});
    const { prompt, options, type, context } = payload;

    let optionsArray = [];
    if (Array.isArray(options)) optionsArray = options;
    else if (typeof options === 'string') {
        try { optionsArray = JSON.parse(options); } catch (e) { optionsArray = options.split(',').map(s => s.trim()); }
    }

    const handleSubmit = async (finalDecision) => {
        setSubmittingAction(finalDecision);
        await onResolve(request.hitl_id, {
            decision: finalDecision,
            comment: ''
        });
        setSubmittingAction(null);
    };

    const getTypeConfig = (t) => {
        switch (t) {
            case 'approve_reject': return { icon: <UserCheck size={16} />, bg: '#f0fdf4', color: '#16a34a' };
            case 'choose': return { icon: <List size={16} />, bg: '#f8fafc', color: '#475569' };
            case 'notify': return { icon: <AlertTriangle size={16} />, bg: '#fffbeb', color: '#d97706' };
            case 'provide_input': return { icon: <HelpCircle size={16} />, bg: '#eff6ff', color: '#2563eb' };
            default: return { icon: <UserCheck size={16} />, bg: '#eff6ff', color: '#2563eb' };
        }
    };

    const config = getTypeConfig(type);

    const LoadingSpinner = () => (
        <div style={{ width: '12px', height: '12px', border: '2px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
    );

    const actionButton = (actionKey, label, icon, onClick, primary = false, color = '#3b82f6') => {
        const isLoading = submittingAction === actionKey;
        const isDisabled = submittingAction !== null;
        return (
            <button
                key={actionKey}
                disabled={isDisabled}
                onClick={(e) => { e.stopPropagation(); onClick(); }}
                style={{
                    display: 'flex', alignItems: 'center', gap: '6px',
                    padding: '6px 12px',
                    fontSize: '12px', fontWeight: 600,
                    borderRadius: '6px',
                    border: primary ? 'none' : `1px solid ${color}40`,
                    background: primary ? color : 'white',
                    color: primary ? 'white' : color,
                    cursor: isDisabled ? 'not-allowed' : 'pointer',
                    opacity: isDisabled && !isLoading ? 0.5 : 1,
                    transition: 'all 0.2s',
                    boxShadow: primary ? `0 1px 2px ${color}30` : 'none'
                }}
                onMouseEnter={e => {
                    if (!isDisabled) e.currentTarget.style.background = primary ? `${color}e0` : `${color}10`;
                }}
                onMouseLeave={e => {
                    if (!isDisabled) e.currentTarget.style.background = primary ? color : 'white';
                }}
            >
                {isLoading ? <LoadingSpinner /> : icon}
                {label}
            </button>
        );
    };

    const renderActions = () => {
        if (type === 'approve_reject') {
            return (
                <div style={{ display: 'flex', gap: '8px' }}>
                    {actionButton('approved', 'Approve', <Check size={14} />, () => handleSubmit('approved'), true, '#10b981')}
                    {actionButton('rejected', 'Reject', <X size={14} />, () => handleSubmit('rejected'), false, '#ef4444')}
                </div>
            );
        }
        if (type === 'choose') {
            if (optionsArray && optionsArray.length > 0) {
                return optionsArray.map(opt => actionButton(opt, opt, null, () => handleSubmit(opt), false, '#64748b'));
            }
            return actionButton('reply', 'Reply in Chat', <MessageSquare size={14} />, () => navigate(`/sessions/${request.session_id}`), true, '#1e293b');
        }
        if (type === 'notify') {
            return actionButton('acknowledged', 'Acknowledge', <Check size={14} />, () => handleSubmit('acknowledged'), true, '#3b82f6');
        }
        if (type === 'provide_input') {
            return actionButton('reply', 'Reply in Chat', <MessageSquare size={14} />, () => navigate(`/sessions/${request.session_id}`), true, '#1e293b');
        }
        return null;
    };

    return (
        <div
            onClick={() => navigate(`/sessions/${request.session_id}`)}
            style={{
                display: 'flex',
                padding: '16px',
                gap: '16px',
                background: 'white',
                transition: 'background 0.2s',
                cursor: 'pointer',
                position: 'relative'
            }}
            onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
            onMouseLeave={e => e.currentTarget.style.background = 'white'}
        >
            {/* Icon */}
            <div style={{
                width: '32px', height: '32px', borderRadius: '8px',
                background: config.bg, color: config.color,
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0
            }}>
                {config.icon}
            </div>

            {/* Main Content */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px' }}>
                    <div style={{ fontSize: '14px', fontWeight: 600, color: '#0f172a', lineHeight: '1.4', wordBreak: 'break-word' }}>
                        {prompt || 'Action Required'}
                    </div>
                </div>

                {context && (
                    <div style={{
                        fontSize: '12px', color: '#64748b', lineHeight: '1.5',
                        display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', textOverflow: 'ellipsis',
                        background: '#f1f5f9', padding: '8px 12px', borderRadius: '6px'
                    }}>
                        {context}
                    </div>
                )}

                {/* Actions Inline */}
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '4px' }}>
                    {renderActions()}
                </div>
            </div>

            {/* Header Right Edge */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', justifyContent: 'flex-start', flexShrink: 0 }}>
                <div style={{
                    fontSize: '11px', fontWeight: 600, color: '#94a3b8',
                    display: 'flex', alignItems: 'center', gap: '4px',
                    padding: '4px 8px', borderRadius: '6px',
                    background: '#f1f5f9'
                }}>
                    ID: {request.session_id.substring(0, 6).toUpperCase()}
                    <ExternalLink size={10} />
                </div>
            </div>

            {/* Right arrow indicator on hover (subtle) */}
            <div style={{
                position: 'absolute', right: '16px', top: '50%', transform: 'translateY(-50%)',
                color: '#cbd5e1', opacity: 0, transition: 'opacity 0.2s',
                pointerEvents: 'none'
            }} className="jump-hint">
                <ArrowRight size={16} />
            </div>
            <style>{`
                div:hover > .jump-hint { opacity: 0.5; }
            `}</style>
        </div>
    );
};
