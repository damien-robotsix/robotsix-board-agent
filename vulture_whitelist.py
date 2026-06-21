# vulture_whitelist.py
# Suppress false positives from the OP_TABLE dispatch pattern.

# -- private handlers (referenced only in OP_TABLE dict literal) -----------
_list_tickets
_get_ticket
_board_cards
_history
_merge_status
_description
_create_ticket
_add_comment
_transition
_approve
_mark_done
_merge_now
_resume_blocked
_migrate
_set_priority

# -- Pydantic args models (used only via .model_validate() in handlers) -----
ListTicketsArgs
GetTicketArgs
BoardCardsArgs
HistoryArgs
MergeStatusArgs
DescriptionArgs
CreateTicketArgs
AddCommentArgs
TransitionArgs
ApproveArgs
MarkDoneArgs
MergeNowArgs
ResumeBlockedArgs
MigrateArgs
SetPriorityArgs

# -- agent.py indirect references ------------------------------------------
_handle_request

# -- brokered.py: public API consumed by mill, not within board-agent ------
BrokeredBoardResponder

# -- board_manager.py: public API consumed by mill + the CLI ---------------
BoardManager

# -- board_manager.py: retained for API compatibility (set but not read) ---
_openrouter_key
