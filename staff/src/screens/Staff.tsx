import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { StaffError, getStaff, searchUsers, setRole } from '../api';
import { errorText } from '../logic';
import type { Lang, StaffMember, UserHit } from '../types';
import { Notice, ReauthDialog, makeT } from '../ui';

type RoleChoice = 'moderator' | 'superadmin' | null;

/**
 * Staff roles (Moderation spec 2.2 and 6.1), superadmin only. Each change needs the password again
 * (and the authenticator code), is serialised on the server, and can never remove the last superadmin.
 */
export function StaffRoles({ lang, hasAuthenticator }: { lang: Lang; hasAuthenticator: boolean }) {
  const t = makeT(lang);
  const [staff, setStaff] = useState<StaffMember[] | null>(null);
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<UserHit[] | null>(null);
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState<{ tone: 'error' | 'success'; text: string } | null>(null);
  const [pending, setPending] = useState<{ userId: string; role: RoleChoice } | null>(null);
  const [needReauth, setNeedReauth] = useState(false);

  const load = useCallback(async () => {
    try {
      setStaff((await getStaff()).items);
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure, lang) });
    }
  }, [lang]);

  useEffect(() => {
    void load();
  }, [load]);

  const find = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setHits((await searchUsers(query.trim())).items);
      setMessage(null);
    } catch (failure) {
      setMessage({ tone: 'error', text: errorText(failure, lang) });
    }
  };

  const apply = async (userId: string, role: RoleChoice) => {
    if (reason.trim().length < 3) {
      setMessage({ tone: 'error', text: t('কারণ লিখুন (কমপক্ষে ৩ অক্ষর)।', 'Write a reason (at least 3 characters).') });
      return;
    }
    try {
      await setRole(userId, role, reason.trim());
      setMessage({ tone: 'success', text: t('ভূমিকা হালনাগাদ হয়েছে।', 'Role updated.') });
      setPending(null);
      setNeedReauth(false);
      setHits(null);
      await load();
    } catch (failure) {
      if (failure instanceof StaffError && failure.code === 'REAUTH_REQUIRED') {
        setPending({ userId, role });
        setNeedReauth(true);
        return;
      }
      setMessage({ tone: 'error', text: errorText(failure, lang) });
    }
  };

  return (
    <div className="stack">
      {message && <Notice tone={message.tone}>{message.text}</Notice>}
      {needReauth && pending && (
        <ReauthDialog
          lang={lang}
          needsCode={hasAuthenticator}
          onCancel={() => setNeedReauth(false)}
          onDone={() => void apply(pending.userId, pending.role)}
        />
      )}
      <section className="card stack">
        <h2>{t('সক্রিয় স্টাফ', 'Active staff')}</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('নাম', 'Name')}</th>
                <th>{t('ইমেইল', 'Email')}</th>
                <th>{t('ভূমিকা', 'Role')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {staff?.map((member) => (
                <tr key={member.user_id}>
                  <td>{member.display_name}</td>
                  <td>{member.email}</td>
                  <td>{member.role}</td>
                  <td>
                    <button type="button" className="ghost" onClick={() => void apply(member.user_id, null)}>
                      {t('সরান', 'Revoke')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card stack">
        <h2>{t('ভূমিকা দিন', 'Grant a role')}</h2>
        <label htmlFor="role-reason">{t('কারণ (অডিট লগে যাবে)', 'Reason (goes to the audit log)')}</label>
        <input id="role-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        <form className="row" onSubmit={find}>
          <input aria-label={t('ইমেইল খুঁজুন', 'Search by email')} placeholder={t('ইমেইলের অংশ (৩+ অক্ষর)', 'Part of an email (3+ characters)')} value={query} onChange={(e) => setQuery(e.target.value)} />
          <button type="submit" className="primary" disabled={query.trim().length < 3}>
            {t('খুঁজুন', 'Search')}
          </button>
        </form>
        {hits?.length === 0 && <p className="muted">{t('কেউ নেই।', 'No match.')}</p>}
        {hits && hits.length > 0 && (
          <ul className="list">
            {hits.map((hit) => (
              <li key={hit.user_id} className="item">
                <span className="item-title">
                  {hit.display_name} · {hit.email}
                </span>
                <span className="row small muted">
                  {hit.role ?? t('ভূমিকা নেই', 'no role')}
                  {(['moderator', 'superadmin'] as const).map((role) => (
                    <button key={role} type="button" className="ghost" disabled={hit.role === role} onClick={() => void apply(hit.user_id, role)}>
                      {role}
                    </button>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
