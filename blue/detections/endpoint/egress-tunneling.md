# Assess whether DNS carries unusual application data

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Does DNS usage differ from the host role in a way consistent with an unintended data channel?

## Evidence to request

Query and response records, client/resolver identities, query type, parent-name derivation method, lengths and response outcomes; endpoint process or resolver configuration.

## Reasoning procedure

- Aggregate distinct full query names, label lengths and total observed traffic per client and correctly derived parent domain. Public-suffix handling and internal zones affect grouping.
- Character entropy can supplement label length and uniqueness, but depends on the alphabet and sample length. Compare comparable labels and avoid a universal entropy cutoff. Long random-looking names are not proof of encoded confidential data.
- Compare both query and response behavior. High uniqueness or long labels can reflect tracking, content delivery, antimalware or service discovery.
- Retain unsuccessful queries and retransmissions separately. A large count of retries is not an equal number of new data transfers.
- Correlate the requester process and any resulting file/network behavior. DNS structure alone cannot establish what information crossed the boundary.
- Record encrypted resolver paths and resolver caching as visibility limits. Absence in one network sensor does not cover all DNS transport.

## Alternatives and limits

Software agents, telemetry services and security lookups can resemble encoded exchanges. A newly observed resolver may be an approved migration. Protocol classification does not identify attacker intent.

## Discriminating checks

Test ordinary CDN names, repeated failed queries, internal-zone names and high-cardinality synthetic traffic. Confirm the denominator is known clients and the chosen observation window. Resolver policy changes require infrastructure approval.

## Concrete observation contract

For DNS, keep Zeek connection `uid`, `trans_id`, `query`, `qtype_name`, `rcode_name`,
`answers` and event time. The same UID can carry several transactions. Attribute a
recursive resolver's traffic to a client only with resolver or host evidence; a resolver
address alone is not the originating workstation. Sysmon 22 can provide `QueryName`,
`QueryStatus`, `QueryResults` and `ProcessGuid` where its collection is configured.

State the public-suffix list/version and treatment of private suffixes when grouping
domains. Entropy, label length, NXDOMAIN rates and byte asymmetry need sample counts and
benign service baselines; none alone proves a channel. For ICMP, use actual packet type,
code, direction, payload-length distribution and host/process context if available rather
than inventing DNS fields. Packet/flow summaries can miss content needed for a conclusion.
