from aiogram.fsm.state import State, StatesGroup

class UserStates(StatesGroup):
    # Example state
    waiting_for_vpn_key = State()
    waiting_support_ticket_message = State()

class RenameKey(StatesGroup):
    waiting_for_name = State()

class ReplaceKey(StatesGroup):
    users_server = State()
    users_inbound = State()
    confirm = State()

class NewKeyConfig(StatesGroup):
    waiting_for_server = State()
    waiting_for_inbound = State()


class GiftFlow(StatesGroup):
    waiting_for_recipient_name = State()


class KeyExclusions(StatesGroup):
    waiting_for_rule_value = State()
