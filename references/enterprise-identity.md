# Enterprise identity reference

Use OIDC for human and workload authentication. Validate issuer, signature, approved asymmetric
algorithm, expiration, audience/resource and tenant claims. Never trust unsigned JWT claims.
Use SCIM Users and Groups for activation, deactivation and role membership. An inactive SCIM user
must not retain access merely because an older token remains cryptographically valid.
For high-risk approvals require an OIDC `amr` value such as `webauthn`, `fido2`, `passkey` or
hardware-key evidence. The Skill consumes this evidence; the identity provider performs the actual
phishing-resistant authentication ceremony.
