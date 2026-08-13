import "./ExecutiveCard.css";

const ROLE_META = {
  CEO: {
    name: "Ananya Kapoor",
    title: "Chief Executive Officer",
    lens: "Decision owner",
    initial: "CE",
  },
  CFO: {
    name: "Arjun Mehta",
    title: "Chief Financial Officer",
    lens: "Financial perspective",
    initial: "CF",
  },
  CMO: {
    name: "Riya Sharma",
    title: "Chief Marketing Officer",
    lens: "Growth & customer perspective",
    initial: "CM",
  },
  COO: {
    name: "Vikram Nair",
    title: "Chief Operating Officer",
    lens: "Operations perspective",
    initial: "CO",
  },
  CSO: {
    name: "Aditya Iyer",
    title: "Chief Strategy Officer",
    lens: "Strategy perspective",
    initial: "CS",
  },
  SYNTHESIS: {
    title: "Board Synthesis",
    lens: "Integrated recommendation",
    initial: "BR",
  },
};

export function executiveDisplayName(role, speaker) {
  const meta = ROLE_META[role];
  if (speaker && speaker !== role) return speaker;
  return meta?.name || meta?.title || role;
}

function ExecutiveCard({ role, content, round, speaker }) {
  const meta = ROLE_META[role] || {
    title: role,
    lens: "Board contribution",
    initial: role.slice(0, 2),
  };

  return (
    <article className={`exec-card role-${role.toLowerCase()}`}>
      <div className="exec-card-top">
        <div className={`exec-avatar role-${role.toLowerCase()}`}>{meta.initial}</div>
        <div>
          <div className="exec-heading">
          <span className={`role-badge ${role.toLowerCase()}`}>{role}</span>
          {round != null ? <span className="round-chip">Round {round}</span> : null}
        </div>
          <h4>{executiveDisplayName(role, speaker)}</h4>
          <p className="exec-lens">{meta.lens}</p>
        </div>
      </div>
      <div className="exec-body">{content}</div>
    </article>
  );
}

export default ExecutiveCard;
