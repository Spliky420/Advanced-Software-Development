// Release 0 is single-user: the backend scopes every unfiltered query to its
// own DEFAULT_USER_ID, and this is the matching value on the client. It is
// sent explicitly rather than left implicit so that swapping in a real signed
// in user later is a change to this one import, not a hunt through the pages.
export const DEFAULT_USER_ID = 1
