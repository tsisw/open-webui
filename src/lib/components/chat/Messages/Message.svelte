<script lang="ts">
        console.error("✅ Message.svelte loaded");
	import { toast } from 'svelte-sonner';

	import { tick, getContext, onMount, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	import { settings } from '$lib/stores';
	import { copyToClipboard } from '$lib/utils';

	import MultiResponseMessages from './MultiResponseMessages.svelte';
	import ResponseMessage from './ResponseMessage.svelte';
	import UserMessage from './UserMessage.svelte';

	export let chatId;
	export let selectedModels = [];
	export let idx = 0;

	export let history;
	export let messageId;

	export let user;

	export let setInputText: Function = () => {};
	export let gotoMessage;
	export let showPreviousMessage;
	export let showNextMessage;
	export let updateChat;

	export let editMessage;
	export let saveMessage;
	export let deleteMessage;
	export let rateMessage;
	export let actionMessage;
	export let submitMessage;

	export let regenerateResponse;
	export let continueResponse;
	export let mergeResponses;

	export let addMessages;
	export let triggerScroll;
	export let readOnly = false;
</script>

<div
	class="flex flex-col justify-between px-5 mb-3 w-full {($settings?.widescreenMode ?? null)
		? 'max-w-full'
		: 'max-w-5xl'} mx-auto rounded-lg group"
>
	{#if history.messages[messageId]}
		{#if history.messages[messageId].role === 'user'}
			<UserMessage
				{user}
				{history}
				{messageId}
				isFirstMessage={idx === 0}
				siblings={history.messages[messageId].parentId !== null
					? (history.messages[history.messages[messageId].parentId]?.childrenIds ?? [])
					: (Object.values(history.messages)
							.filter((message) => message.parentId === null)
							.map((message) => message.id) ?? [])}
				{gotoMessage}
				{showPreviousMessage}
				{showNextMessage}
				{editMessage}
				{deleteMessage}
				{readOnly}
			/>
		{:else if (history.messages[history.messages[messageId].parentId]?.models?.length ?? 1) === 1}
			<ResponseMessage
				{chatId}
				{history}
				{messageId}
				{selectedModels}
				isLastMessage={messageId === history.currentId}
				siblings={history.messages[history.messages[messageId].parentId]?.childrenIds ?? []}
				{setInputText}
				{gotoMessage}
				{showPreviousMessage}
				{showNextMessage}
				{updateChat}
				{editMessage}
				{saveMessage}
				{rateMessage}
				{actionMessage}
				{submitMessage}
				{deleteMessage}
				{continueResponse}
				{regenerateResponse}
				{addMessages}
				{readOnly}
			/>

{console.error("🔍 Checking followups or multi-model condition:", {
  followups: history.messages[messageId]?.followups,
  modelCount: history.messages[history.messages[messageId].parentId]?.models?.length
})}



		{:else if (history.messages[messageId]?.followups || (history.messages[history.messages[messageId].parentId]?.models?.length ?? 1) !== 1)}
                   
{#if history.messages[messageId]?.title}
        <div class="text-sm font-semibold text-blue-600 mb-2">
            🏷️ {history.messages[messageId].title}
        </div>
    {/if}

    {#if history.messages[messageId]?.tags?.length}
        <div class="text-xs text-gray-500 mb-2">
            Tags: {history.messages[messageId].tags.join(', ')}
        </div>
    {/if}
console.error("✅ Rendering MultiResponseMessages.svelte for message:", messageId);


			<MultiResponseMessages
				bind:history
				{chatId}
				{messageId}
				{selectedModels}
				isLastMessage={messageId === history?.currentId}
				{setInputText}
				{updateChat}
				{editMessage}
				{saveMessage}
				{rateMessage}
				{actionMessage}
				{submitMessage}
				{deleteMessage}
				{continueResponse}
				{regenerateResponse}
				{mergeResponses}
				{triggerScroll}
				{addMessages}
				{readOnly}
			/>
		{/if}
	{/if}
</div>
