import { BroadcastList } from "./BroadcastList";

// History is every broadcast that has actually gone out (or tried to) -
// scheduled-but-not-yet-sent ones live on the Scheduled tab instead, so
// there's no status sub-filter here, only search (CommunicationPage already
// excludes 'scheduled' rows from the list this component receives).
export function MessageHistory({ broadcasts, loading, search, onSearchChange, onOpen, onLoadMore, hasMore }) {
  return <BroadcastList
    broadcasts={broadcasts} loading={loading} search={search} onSearchChange={onSearchChange}
    showStatusFilter={false} onOpen={onOpen} onLoadMore={onLoadMore} hasMore={hasMore}
    emptyTitle="No message history yet" emptyDescription="Broadcasts you send or schedule will show their delivery status here."
  />;
}
