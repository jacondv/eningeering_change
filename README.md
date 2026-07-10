# Engineering Change / DCR Management

An Odoo 19 addon that digitizes the full lifecycle of an Engineering Change
Request (ECR), from proposal to closure: risk assessment, multi-level
approval, implementation tracking, and evidence-backed sign-off.

## What it does

A request moves through a controlled workflow:

```
Draft -> Manager Approval -> [BOD Approval, DCR only] -> Implement
      -> Production -> Done
```

- **Two request types** - *Minor Change* (Manager approval only) and
  *DCR / Design Change Request* (Manager, then BOD approval).
- **Risk assessment** - RPN scoring with Lead Time / Safety / Compliance
  impact fields, auto-classified into Low/Medium/High.
- **Implementation tracking** - each request has its own Actions/Tasks
  (built on `project.task`), each with assignees, a deadline, and an
  Evidence tab for uploading proof of completion.
- **Guarded workflow transitions** - every state change (submit, approve,
  reject, confirm production, close, reopen) runs through a dedicated
  server action with its own permission check; the `state` field itself
  cannot be edited directly, closing the usual "just write the field"
  bypass. A Manager can revert a request to its previous state to undo an
  accidental click, without going through the full reject flow.
- **Role-based permissions** - View / Request / BOD Approve / Manager
  Approve / Delete groups, plus a per-request *Implement Owner* who alone
  (with Manager) can manage that request's tasks; a task's assignee can
  only update its status and evidence, never its other details.
- **Notifications** - both email and in-app (bell/inbox) notifications at
  every workflow stage, plus overdue-action reminders via a scheduled
  action.
- **Full audit trail** - creation, edits, and status changes on requests,
  tasks, and evidence are all logged to the chatter.
- **Dashboard** - request/task counts by state, type and RPN level,
  overdue items, and a personal "My Open Tasks" list, with click-through
  navigation into the underlying records.
- **PDF report** for a request's full record.

## Tech stack

- Odoo 19 (Community), built on the `project` app for task management
- PostgreSQL
- Docker / Docker Compose for local development
