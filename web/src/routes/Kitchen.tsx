import { AppShell } from '../components/AppShell.tsx'
import { AuthorityBadge } from '../components/AuthorityBadge.tsx'
import { CountBadge } from '../components/CountBadge.tsx'
import { EvidenceQuote } from '../components/EvidenceQuote.tsx'
import { ProposalCard } from '../components/ProposalCard.tsx'
import { RegisterTable } from '../components/RegisterTable.tsx'
import { RelationChip, type RelationLabel } from '../components/RelationChip.tsx'
import { ScopeBar } from '../components/ScopeBar.tsx'
import { Sidecar, SidecarFrame } from '../components/Sidecar.tsx'
import { StateChip, type LifecycleState } from '../components/StateChip.tsx'
import { StatusTag } from '../components/StatusTag.tsx'

const STATES: LifecycleState[] = ['confirmed', 'proposed', 'contradicted', 'superseded', 'withdrawn']
const RELATIONS: RelationLabel[] = ['new', 'refinement', 'contradiction', 'supersession', 'restatement', 'not_requirement']

const quote = {
  speaker: 'Client PO',
  turnId: 'D1-M02:0002',
  before: "Our security team won't sign off on us holding customer passwords, so ",
  span: 'we will use single sign-on instead',
  after: '. Customers authenticate through our existing identity provider.',
}

export function KitchenRoute() {
  return (
    <AppShell projectId="D1" projectName="Client portal" active="home" reviewCount={7}>
      <main style={{ flex: '999 1 560px', minWidth: 0, boxSizing: 'border-box', padding: '40px 48px', display: 'flex', flexDirection: 'column', gap: 28 }}>
        <h1 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 38 }}>Component kitchen</h1>
        <p style={{ margin: 0, fontSize: 14, color: 'var(--ink-meta)' }}>
          Dev only. Not in the product navigation. Sample copy is the D1 export.
        </p>
        <ScopeBar client="Northwind Logistics" projectName="Client portal" count="8 requirement families" />
        <section>
          <h2 style={kicker}>State</h2>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {STATES.map((state) => (
              <StateChip key={state} state={state} />
            ))}
            <span className="cia-chip cia-chip--empty">Empty</span>
          </div>
        </section>
        <section>
          <h2 style={kicker}>Status and count</h2>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <StatusTag tone="on">Connected</StatusTag>
            <StatusTag tone="off">Not capturing</StatusTag>
            <StatusTag tone="live">Capturing</StatusTag>
            <CountBadge count={7} />
          </div>
        </section>
        <section>
          <h2 style={kicker}>Relation</h2>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {RELATIONS.map((relation) => (
              <RelationChip key={relation} relation={relation} />
            ))}
          </div>
        </section>
        <section>
          <h2 style={kicker}>Authority</h2>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <AuthorityBadge can>Can confirm scope</AuthorityBadge>
            <AuthorityBadge can={false}>Cannot confirm scope</AuthorityBadge>
          </div>
        </section>
        <section>
          <h2 style={kicker}>Evidence</h2>
          <EvidenceQuote {...quote} onJump={() => undefined} />
        </section>
        <section>
          <h2 style={kicker}>Register</h2>
          <RegisterTable
            rows={STATES.map((state) => ({
              key: state,
              versionLabel: `R0${STATES.indexOf(state) + 1} v1`,
              text: `Sample ${state} requirement`,
              state,
              changedLabel: 'M02 · 18 Mar',
              note: state === 'contradicted' ? 'Challenged in M02 — no replacement stated' : null,
              href: '/projects/D1/register',
            }))}
          />
        </section>
        <section>
          <h2 style={kicker}>Proposal, confirm held</h2>
          <ProposalCard
            scopeLabel="Client portal / R03 v1"
            statement="The password reset email may no longer be required under SSO."
            unresolved
            relation="contradiction"
            proposalStatus="proposed"
            toState="contradicted"
            evidence={[
              {
                speaker: 'Client Dev',
                turnId: 'D1-M02:0006',
                before: 'It does, but ',
                span: "I'd want to confirm that with the identity provider team before you write it off",
                after: '. Leave it open for now.',
              },
            ]}
            speakerName="Tom Alder"
            speakerRole="engineer"
            speakerCanConfirm={false}
            authorityNote="Tom Alder (engineer) cannot confirm scope"
            rationale="The obligation is challenged but no replacement is stated, and the speaker cannot confirm scope. Classified as contradiction rather than supersession."
            retrieved={[
              { rank: 1, text: 'The system sends a password reset email containing a reset link', state: 'proposed', chosen: true },
              { rank: 2, text: 'On dispatch, the customer receives an order receipt email with line items and tracking number', state: 'confirmed', chosen: false },
              { rank: 3, text: 'Customers authenticate with an email address and password', state: 'superseded', chosen: false },
              { rank: 4, text: 'Passwords must be at least twelve characters', state: 'withdrawn', chosen: false },
            ]}
            canConfirm={false}
            canConfirmReason="Needs confirmation from a scope owner"
            decided={false}
            onConfirm={() => undefined}
            onReject={() => undefined}
            onEdit={() => undefined}
            onJump={() => undefined}
          />
        </section>
        <section>
          <h2 style={kicker}>Proposal, confirm allowed</h2>
          <ProposalCard
            scopeLabel="Client portal / R01 v2"
            statement="Customers authenticate through the existing identity provider using SSO."
            unresolved={false}
            relation="supersession"
            proposalStatus="proposed"
            toState="superseded"
            evidence={[quote]}
            speakerName="Priya Raman"
            speakerRole="Product owner"
            speakerCanConfirm
            rationale="The client product owner replaces email-and-password login with single sign-on."
            retrieved={[{ rank: 1, text: 'Customers authenticate with an email address and password', state: 'confirmed', chosen: true }]}
            canConfirm
            canConfirmReason=""
            decided={false}
            onConfirm={() => undefined}
            onReject={() => undefined}
            onEdit={() => undefined}
          />
        </section>
        <section>
          <h2 style={kicker}>Sidecar</h2>
          <SidecarFrame>
            <img src="/assets/consultsi.png" alt="Consult SI" style={{ height: 17, width: 'auto', display: 'block' }} />
            <div style={kicker}>Pill — anchors bottom-centre, moves to the edge on focus loss</div>
            <Sidecar
              pillLabel="Capturing · 18:42"
              turnCount="47 turns"
              title="Client portal · meeting 3"
              clock="18:42"
              turns={[
                { speaker: 'Client Dev · 16:48', text: "Our security team won't sign off on us holding customer passwords at all." },
                { speaker: 'Client PO · 17:11', text: 'So we will use single sign-on instead.' },
                { speaker: 'Consultant A · 18:40', text: "That's a significant change from the last", partial: true },
              ]}
              scope={[
                { id: 'R04', text: 'Order history view', state: 'confirmed' },
                { id: 'R01', text: 'Email and password login', state: 'confirmed' },
                { id: 'R03', text: 'Password reset email', state: 'contradicted' },
                { id: 'R02', text: 'Twelve-character passwords', state: 'withdrawn' },
              ]}
              endHref="/projects/D1/capture"
              registerHref="/projects/D1/register"
            />
            <p style={{ margin: 0, fontSize: 13, lineHeight: '21px', color: 'var(--ink-meta)' }}>
              Transcript streams; reasoning waits. The panel shows what was already agreed, which is what a consultant
              actually needs mid-argument — and shows no extraction count, no running tally, nothing the model thinks
              about this call.
            </p>
          </SidecarFrame>
        </section>
      </main>
    </AppShell>
  )
}

const kicker = {
  margin: 0,
  fontSize: 11,
  fontWeight: 500,
  letterSpacing: '0.08em',
  textTransform: 'uppercase' as const,
  color: 'var(--ink-meta)',
}
