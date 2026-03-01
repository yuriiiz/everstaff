import React from 'react';
import { Plus } from 'lucide-react';

const EmptyState = ({
    icon: Icon,
    title,
    description,
    actionLabel,
    onAction,
    secondaryActionLabel,
    onSecondaryAction
}) => {
    return (
        <div style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '40px',
            textAlign: 'center',
            background: 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)',
        }} className="fade-in">
            <div style={{
                width: '80px',
                height: '80px',
                borderRadius: '24px',
                background: 'linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '24px',
                boxShadow: '0 10px 15px -3px rgba(186, 230, 253, 0.5), 0 4px 6px -2px rgba(186, 230, 253, 0.2)',
                border: '1px solid #bae6fd',
                animation: 'pulse-subtle 3s ease-in-out infinite'
            }}>
                {Icon && <Icon size={40} style={{ color: '#0ea5e9' }} />}
            </div>

            <style>{`
                @keyframes pulse-subtle {
                    0%, 100% { transform: translateY(0); }
                    50% { transform: translateY(-4px); }
                }
            `}</style>

            <h3 style={{
                fontSize: '20px',
                fontWeight: 700,
                color: '#1e293b',
                marginBottom: '12px',
                letterSpacing: '-0.02em'
            }}>
                {title}
            </h3>

            <p style={{
                fontSize: '14px',
                color: '#64748b',
                maxWidth: '420px',
                lineHeight: '1.6',
                marginBottom: '32px'
            }}>
                {description}
            </p>

            <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                {actionLabel && (
                    <button
                        onClick={onAction}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            padding: '12px 24px',
                            background: '#111827',
                            color: 'white',
                            border: 'none',
                            borderRadius: '12px',
                            fontSize: '14px',
                            fontWeight: 600,
                            cursor: 'pointer',
                            transition: 'all 0.2s ease',
                            boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)'
                        }}
                        onMouseOver={e => {
                            e.currentTarget.style.transform = 'translateY(-1px)';
                            e.currentTarget.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)';
                        }}
                        onMouseOut={e => {
                            e.currentTarget.style.transform = 'translateY(0)';
                            e.currentTarget.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)';
                        }}
                    >
                        <Plus size={18} />
                        {actionLabel}
                    </button>
                )}

                {secondaryActionLabel && (
                    <button
                        onClick={onSecondaryAction}
                        style={{
                            padding: '12px 24px',
                            background: 'white',
                            color: '#475569',
                            border: '1px solid #e2e8f0',
                            borderRadius: '12px',
                            fontSize: '14px',
                            fontWeight: 600,
                            cursor: 'pointer',
                            transition: 'all 0.2s ease'
                        }}
                        onMouseOver={e => {
                            e.currentTarget.style.background = '#f8fafc';
                            e.currentTarget.style.borderColor = '#cbd5e1';
                        }}
                        onMouseOut={e => {
                            e.currentTarget.style.background = 'white';
                            e.currentTarget.style.borderColor = '#e2e8f0';
                        }}
                    >
                        {secondaryActionLabel}
                    </button>
                )}
            </div>
        </div>
    );
};

export default EmptyState;
