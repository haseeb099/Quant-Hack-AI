// DWX_ZeroMQ_Server.mq5
// QuantAI MT5 ZeroMQ bridge — PUSH 32768, PULL 32769, PUB 32770
// Requires ZMQ library for MQL5 (https://github.com/dingmaotu/mql-zmq)

#property service
#property copyright "QuantAI"
#property version   "1.0"

#include <Zmq/Zmq.mqh>
#include <Trade\Trade.mqh>

#define ZMQ_COMMAND_PORT 32768
#define ZMQ_CONFIRM_PORT 32769
#define ZMQ_TICK_PORT    32770
#define MAX_RETRIES      3
#define SLIPPAGE_POINTS  10
#define RECV_TIMEOUT_MS  500
#define CONFIRM_SEND_RETRIES 100
#define CONFIRM_SEND_SLEEP_MS 50

Context *context;
Socket  *push_socket;   // receives commands from Python
Socket  *pull_socket;   // sends confirmations to Python
Socket  *pub_socket;    // publishes ticks
CTrade   g_trade;

string  last_error = "";

//+------------------------------------------------------------------+
void OnStart()
{
   context = new Context();
   push_socket = new Socket(*context, ZMQ_PULL);
   pull_socket = new Socket(*context, ZMQ_PUSH);
   pub_socket  = new Socket(*context, ZMQ_PUB);

   if(!push_socket.bind(StringFormat("tcp://*:%d", ZMQ_COMMAND_PORT)))
   {
      Print("Failed to bind PUSH port ", ZMQ_COMMAND_PORT);
      return;
   }
   if(!pull_socket.bind(StringFormat("tcp://*:%d", ZMQ_CONFIRM_PORT)))
   {
      Print("Failed to bind PULL port ", ZMQ_CONFIRM_PORT);
      return;
   }
   if(!pub_socket.bind(StringFormat("tcp://*:%d", ZMQ_TICK_PORT)))
   {
      Print("Failed to bind PUB port ", ZMQ_TICK_PORT);
      return;
   }

   push_socket.setReceiveTimeout(RECV_TIMEOUT_MS);
   pull_socket.setSendTimeout(5000);
   pull_socket.setLinger(1000);

   Print("QuantAI ZeroMQ Server started on ports ", ZMQ_COMMAND_PORT, "-", ZMQ_TICK_PORT);

   while(!IsStopped())
   {
      ZmqMsg msg;
      if(!push_socket.recv(msg, false))
      {
         PublishTicks();
         continue;
      }
      if(msg.size() <= 0)
      {
         PublishTicks();
         continue;
      }

      string request = msg.getData();
      Print("ZeroMQ request: ", StringSubstr(request, 0, 120));
      string response = ProcessRequest(request);
      if(!SendConfirmation(response))
         Print("Failed to send confirmation");
      PublishTicks();
   }
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   delete push_socket;
   delete pull_socket;
   delete pub_socket;
   delete context;
   Print("QuantAI ZeroMQ Server stopped");
}

//+------------------------------------------------------------------+
bool SendConfirmation(string response)
{
   ZmqMsg reply(response);
   for(int attempt = 0; attempt < CONFIRM_SEND_RETRIES; attempt++)
   {
      if(pull_socket.send(reply, false))
         return true;
      Sleep(CONFIRM_SEND_SLEEP_MS);
   }
   return false;
}

//+------------------------------------------------------------------+
string ProcessRequest(string json)
{
   ulong start_ms = GetTickCount64();
   string action = JsonGet(json, "action");

   if(action == "TRADE")
      return HandleTrade(json, start_ms);
   if(action == "ACCOUNT")
      return HandleAccount(start_ms);
   if(action == "DATA")
      return HandleData(json, start_ms);
   if(action == "POSITIONS")
      return HandlePositions(start_ms);
   if(action == "CLOSE_ALL")
      return HandleCloseAll(start_ms);
   if(action == "SYMBOL_INFO")
      return HandleSymbolInfo(json, start_ms);

   return BuildError("Unknown action: " + action, start_ms);
}

//+------------------------------------------------------------------+
ulong ResolvePositionTicket(string mt5_symbol, ulong order_ticket)
{
   datetime latest_time = 0;
   ulong pos_ticket = order_ticket;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != mt5_symbol) continue;
      datetime open_time = (datetime)PositionGetInteger(POSITION_TIME);
      if(open_time >= latest_time)
      {
         latest_time = open_time;
         pos_ticket = ticket;
      }
   }
   return pos_ticket;
}

//+------------------------------------------------------------------+
string HandleTrade(string json, ulong start_ms)
{
   string symbol  = JsonGet(json, "symbol");
   string type    = JsonGet(json, "type");
   double volume  = StringToDouble(JsonGet(json, "volume"));
   double sl      = StringToDouble(JsonGet(json, "sl"));
   double tp      = StringToDouble(JsonGet(json, "tp"));
   long   ticket  = (long)StringToInteger(JsonGet(json, "ticket"));

   string mt5_symbol = SymbolMap(symbol);
   if(type != "MODIFY" && type != "CLOSE")
   {
      if(!SymbolSelect(mt5_symbol, true))
         return BuildError("Symbol not found: " + symbol, start_ms);
   }

   MqlTradeRequest req = {};
   MqlTradeResult  res = {};
   req.symbol   = mt5_symbol;
   req.volume   = volume;
   req.deviation = SLIPPAGE_POINTS;
   req.magic    = 20260621;
   req.type_filling = ORDER_FILLING_IOC;

   if(type == "MODIFY" && ticket > 0)
   {
      if(!PositionSelectByTicket(ticket))
         return BuildError("Position not found: " + IntegerToString(ticket), start_ms);
      symbol = PositionGetString(POSITION_SYMBOL);
      req.symbol = symbol;
      req.action = TRADE_ACTION_SLTP;
      req.position = ticket;
      req.sl = sl;
      req.tp = tp;

      for(int retry = 0; retry < MAX_RETRIES; retry++)
      {
         if(OrderSend(req, res))
         {
            ulong latency = GetTickCount64() - start_ms;
            return StringFormat(
               "{\"status\":\"ok\",\"action\":\"TRADE\",\"type\":\"MODIFY\",\"symbol\":\"%s\","
               "\"ticket\":%d,\"sl\":%.5f,\"tp\":%.5f,\"slippage\":0.0,\"fill_rate\":1.0,"
               "\"latency_ms\":%d,\"retries\":%d}",
               symbol, ticket, sl, tp, (int)latency, retry);
         }
         last_error = res.comment;
         if(!IsRetryableRetcode(res.retcode))
            break;
         Sleep(200);
      }
      return BuildError("Modify failed: " + last_error, start_ms);
   }
   else if((type == "CLOSE_PARTIAL" || type == "CLOSE") && ticket > 0)
   {
      if(!PositionSelectByTicket(ticket))
         return BuildError("Position not found: " + IntegerToString(ticket), start_ms);
      symbol = PositionGetString(POSITION_SYMBOL);
      req.symbol = symbol;
      double pos_vol = PositionGetDouble(POSITION_VOLUME);
      double close_vol = (type == "CLOSE_PARTIAL" && volume > 0) ? volume : pos_vol;
      if(type == "CLOSE" && volume > 0 && volume < pos_vol)
         close_vol = volume;
      if(close_vol <= 0 || close_vol > pos_vol)
         close_vol = pos_vol;

      long margin_mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
      bool success = false;
      double remaining_vol = pos_vol;
      int retries_used = 0;
      double fill_price = 0;

      if(margin_mode == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING && close_vol < pos_vol)
      {
         g_trade.SetExpertMagicNumber(20260621);
         g_trade.SetDeviationInPoints(SLIPPAGE_POINTS);
         for(int retry = 0; retry < MAX_RETRIES; retry++)
         {
            retries_used = retry;
            if(g_trade.PositionClosePartial(ticket, close_vol))
            {
               success = true;
               fill_price = g_trade.ResultPrice();
               break;
            }
            last_error = g_trade.ResultComment();
            Sleep(200);
         }
         if(PositionSelectByTicket(ticket))
            remaining_vol = PositionGetDouble(POSITION_VOLUME);
         else
            remaining_vol = 0;
      }
      else
      {
         req.action = TRADE_ACTION_DEAL;
         req.position = ticket;
         req.type = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
         req.volume = close_vol;
         req.type_filling = ORDER_FILLING_IOC;

         for(int retry = 0; retry < MAX_RETRIES; retry++)
         {
            retries_used = retry;
            if(OrderSend(req, res))
            {
               success = true;
               fill_price = res.price;
               break;
            }
            last_error = res.comment;
            if(IsRetryableRetcode(res.retcode))
            {
               Sleep(200);
               continue;
            }
            if(req.type_filling == ORDER_FILLING_IOC)
            {
               req.type_filling = ORDER_FILLING_RETURN;
               continue;
            }
            break;
         }
         remaining_vol = pos_vol - close_vol;
         if(remaining_vol < 0) remaining_vol = 0;
         if(PositionSelectByTicket(ticket))
            remaining_vol = PositionGetDouble(POSITION_VOLUME);
         else
            remaining_vol = 0;
      }

      ulong latency = GetTickCount64() - start_ms;
      if(success)
      {
         return StringFormat(
            "{\"status\":\"ok\",\"action\":\"TRADE\",\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.4f,"
            "\"ticket\":%d,\"price\":%.5f,\"remaining_volume\":%.4f,\"slippage\":0.0,\"fill_rate\":1.0,"
            "\"latency_ms\":%d,\"retries\":%d}",
            symbol, type, close_vol, ticket, fill_price, remaining_vol, (int)latency, retries_used);
      }
      return BuildError("Close failed: " + last_error, start_ms);
   }
   else if(type == "CANCEL_PENDING")
   {
      long order_ticket = (long)StringToInteger(JsonGet(json, "order_ticket"));
      if(order_ticket <= 0)
         return BuildError("Missing order_ticket for CANCEL_PENDING", start_ms);
      bool deleted = g_trade.OrderDelete((ulong)order_ticket);
      ulong latency = GetTickCount64() - start_ms;
      if(deleted)
         return StringFormat(
            "{\"status\":\"ok\",\"action\":\"TRADE\",\"type\":\"CANCEL_PENDING\",\"order_ticket\":%d,\"latency_ms\":%d}",
            order_ticket, (int)latency);
      return BuildError("Cancel pending failed: " + IntegerToString(GetLastError()), start_ms);
   }
   else if(type == "BUY" || type == "SELL")
   {
      string entry_mode = JsonGet(json, "entry_mode");
      double limit_price = StringToDouble(JsonGet(json, "limit_price"));
      if(entry_mode == "limit" && limit_price > 0)
      {
         req.action = TRADE_ACTION_PENDING;
         req.type = (type == "BUY") ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
         req.price = limit_price;
         req.type_time = ORDER_TIME_GTC;
      }
      else
      {
         req.action = TRADE_ACTION_DEAL;
         req.type = (type == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      }
      if(sl > 0) req.sl = sl;
      if(tp > 0) req.tp = tp;
   }
   else
      return BuildError("Invalid trade type: " + type, start_ms);

   double expected_price = 0;
   if(req.type == ORDER_TYPE_BUY)
      expected_price = SymbolInfoDouble(req.symbol, SYMBOL_ASK);
   else if(req.type == ORDER_TYPE_SELL)
      expected_price = SymbolInfoDouble(req.symbol, SYMBOL_BID);

   bool success = false;
   int retries_used = 0;
   for(int retry = 0; retry < MAX_RETRIES; retry++)
   {
      retries_used = retry;
      if(OrderSend(req, res))
      {
         success = true;
         break;
      }
      last_error = res.comment;
      if(IsRetryableRetcode(res.retcode))
      {
         Sleep(200);
         if(req.type == ORDER_TYPE_BUY)
            req.price = SymbolInfoDouble(mt5_symbol, SYMBOL_ASK);
         else if(req.type == ORDER_TYPE_SELL)
            req.price = SymbolInfoDouble(mt5_symbol, SYMBOL_BID);
         continue;
      }
      break;
   }

   ulong latency = GetTickCount64() - start_ms;
   double fill_price = res.price;
   double slippage = (expected_price > 0) ? MathAbs(fill_price - expected_price) : 0;

   if(success)
   {
      string entry_mode = JsonGet(json, "entry_mode");
      double limit_price = StringToDouble(JsonGet(json, "limit_price"));
      if((type == "BUY" || type == "SELL") && entry_mode == "limit" && limit_price > 0)
      {
         return StringFormat(
            "{\"status\":\"ok\",\"action\":\"TRADE\",\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.4f,"
            "\"order_ticket\":%d,\"order_pending\":true,\"price\":%.5f,\"latency_ms\":%d,\"retries\":%d}",
            symbol, type, volume, res.order, limit_price, (int)latency, retries_used);
      }
      ulong position_ticket = res.order;
      double filled_volume = volume;
      if(type == "BUY" || type == "SELL")
      {
         position_ticket = ResolvePositionTicket(mt5_symbol, res.order);
         if(PositionSelectByTicket(position_ticket))
            filled_volume = PositionGetDouble(POSITION_VOLUME);
      }
      return StringFormat(
         "{\"status\":\"ok\",\"action\":\"TRADE\",\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.4f,"
         "\"ticket\":%d,\"price\":%.5f,\"slippage\":%.5f,\"fill_rate\":1.0,\"latency_ms\":%d,\"retries\":%d}",
         symbol, type, filled_volume, position_ticket, fill_price, slippage, (int)latency, retries_used);
   }

   return BuildError("Trade failed: " + last_error, start_ms);
}

//+------------------------------------------------------------------+
string HandleAccount(ulong start_ms)
{
   double equity  = AccountInfoDouble(ACCOUNT_EQUITY);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double margin  = AccountInfoDouble(ACCOUNT_MARGIN);
   double free    = AccountInfoDouble(ACCOUNT_MARGIN_FREE);

   double gross_exposure = 0;
   double largest_pct = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      double vol = PositionGetDouble(POSITION_VOLUME);
      double price = PositionGetDouble(POSITION_PRICE_OPEN);
      double contract = SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
      if(contract <= 0) contract = 1.0;
      double pos_value = vol * contract * price;
      gross_exposure += pos_value;
      double pct = (equity > 0) ? pos_value / equity : 0;
      if(pct > largest_pct) largest_pct = pct;
   }

   double margin_level = (margin > 0) ? (equity / margin * 100.0) : 9999.0;
   long margin_mode = AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   double stop_out_so = AccountInfoDouble(ACCOUNT_MARGIN_SO_SO);

   bool trade_allowed = (bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)
      && (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)
      && (bool)MQLInfoInteger(MQL_TRADE_ALLOWED);

   ulong latency = GetTickCount64() - start_ms;
   return StringFormat(
      "{\"status\":\"ok\",\"action\":\"ACCOUNT\",\"equity\":%.2f,\"balance\":%.2f,"
      "\"margin\":%.2f,\"free_margin\":%.2f,\"gross_exposure\":%.2f,"
      "\"largest_position_pct\":%.4f,\"margin_level\":%.2f,"
      "\"margin_mode\":%d,\"stop_out_level\":%.2f,\"trade_allowed\":%s,\"latency_ms\":%d}",
      equity, balance, margin, free, gross_exposure, largest_pct, margin_level,
      (int)margin_mode, stop_out_so, trade_allowed ? "true" : "false", (int)latency);
}

//+------------------------------------------------------------------+
string HandleData(string json, ulong start_ms)
{
   string symbol = JsonGet(json, "symbol");
   string tf_str = JsonGet(json, "timeframe");
   int count = (int)StringToInteger(JsonGet(json, "count"));
   if(count <= 0) count = 200;

   string mt5_symbol = SymbolMap(symbol);
   if(!SymbolSelect(mt5_symbol, true))
      return BuildError("Symbol not in Market Watch: " + symbol, start_ms);

   ENUM_TIMEFRAMES tf = TimeframeMap(tf_str);

   MqlRates rates[];
   int copied = CopyRates(mt5_symbol, tf, 0, count, rates);
   if(copied <= 0)
      copied = CopyRates(mt5_symbol, tf, 1, count, rates);
   if(copied <= 0)
      return BuildError("Failed to copy rates for " + symbol + " (broker=" + mt5_symbol + ")", start_ms);

   string bars = "";
   for(int i = 0; i < copied; i++)
   {
      if(i > 0) bars += ",";
      bars += StringFormat(
         "{\"time\":%d,\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f,\"volume\":%.0f}",
         rates[i].time, rates[i].open, rates[i].high, rates[i].low, rates[i].close, rates[i].tick_volume);
   }

   ulong latency = GetTickCount64() - start_ms;
   return StringFormat(
      "{\"status\":\"ok\",\"action\":\"DATA\",\"symbol\":\"%s\",\"timeframe\":\"%s\",\"count\":%d,"
      "\"bars\":[%s],\"latency_ms\":%d}",
      symbol, tf_str, copied, bars, (int)latency);
}

//+------------------------------------------------------------------+
string HandlePositions(ulong start_ms)
{
   string positions = "";
   int pos_count = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(pos_count > 0) positions += ",";
      string sym = PositionGetString(POSITION_SYMBOL);
      string dir = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      double vol = PositionGetDouble(POSITION_VOLUME);
      double price_open = PositionGetDouble(POSITION_PRICE_OPEN);
      double contract = SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);
      if(contract <= 0) contract = 1.0;
      double notional = vol * contract * price_open;
      positions += StringFormat(
         "{\"ticket\":%d,\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.4f,"
         "\"price_open\":%.5f,\"contract_size\":%.2f,\"notional\":%.2f,"
         "\"sl\":%.5f,\"tp\":%.5f,\"profit\":%.2f}",
         ticket, sym, dir, vol, price_open, contract, notional,
         PositionGetDouble(POSITION_SL), PositionGetDouble(POSITION_TP),
         PositionGetDouble(POSITION_PROFIT));
      pos_count++;
   }

   ulong latency = GetTickCount64() - start_ms;
   return StringFormat(
      "{\"status\":\"ok\",\"action\":\"POSITIONS\",\"count\":%d,\"positions\":[%s],\"latency_ms\":%d}",
      pos_count, positions, (int)latency);
}

//+------------------------------------------------------------------+
string HandleCloseAll(ulong start_ms)
{
   int closed = 0;
   int failed = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      MqlTradeRequest req = {};
      MqlTradeResult  res = {};
      req.action   = TRADE_ACTION_DEAL;
      req.position = ticket;
      req.symbol   = PositionGetString(POSITION_SYMBOL);
      req.volume   = PositionGetDouble(POSITION_VOLUME);
      req.deviation = SLIPPAGE_POINTS;
      req.magic    = 20260621;
      req.type_filling = ORDER_FILLING_IOC;
      req.type = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
         ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;

      bool ok = false;
      for(int retry = 0; retry < MAX_RETRIES; retry++)
      {
         if(OrderSend(req, res))
         {
            ok = true;
            break;
         }
         if(!IsRetryableRetcode(res.retcode))
            break;
         Sleep(200);
      }
      if(ok) closed++;
      else failed++;
   }

   ulong latency = GetTickCount64() - start_ms;
   return StringFormat(
      "{\"status\":\"ok\",\"action\":\"CLOSE_ALL\",\"closed\":%d,\"failed\":%d,\"latency_ms\":%d}",
      closed, failed, (int)latency);
}

//+------------------------------------------------------------------+
string HandleSymbolInfo(string json, ulong start_ms)
{
   string symbol = JsonGet(json, "symbol");
   string mt5_symbol = SymbolMap(symbol);
   if(!SymbolSelect(mt5_symbol, true))
      return BuildError("Symbol not found: " + symbol, start_ms);

   ulong latency = GetTickCount64() - start_ms;
   return StringFormat(
      "{\"status\":\"ok\",\"action\":\"SYMBOL_INFO\",\"symbol\":\"%s\","
      "\"contract_size\":%.2f,\"volume_min\":%.4f,\"volume_step\":%.4f,\"volume_max\":%.2f,"
      "\"digits\":%d,\"point\":%.10f,\"stops_level\":%d,\"latency_ms\":%d}",
      symbol,
      SymbolInfoDouble(mt5_symbol, SYMBOL_TRADE_CONTRACT_SIZE),
      SymbolInfoDouble(mt5_symbol, SYMBOL_VOLUME_MIN),
      SymbolInfoDouble(mt5_symbol, SYMBOL_VOLUME_STEP),
      SymbolInfoDouble(mt5_symbol, SYMBOL_VOLUME_MAX),
      (int)SymbolInfoInteger(mt5_symbol, SYMBOL_DIGITS),
      SymbolInfoDouble(mt5_symbol, SYMBOL_POINT),
      (int)SymbolInfoInteger(mt5_symbol, SYMBOL_TRADE_STOPS_LEVEL),
      (int)latency);
}

//+------------------------------------------------------------------+
void PublishTicks()
{
   static ulong last_pub = 0;
   if(GetTickCount64() - last_pub < 1000) return;
   last_pub = GetTickCount64();

   string competition[] = {
      "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BARUSD",
      "XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY",
      "AUDUSD", "USDCAD", "USDCHF", "EURGBP", "EURCHF"
   };

   string tick_data = "";
   int n = 0;
   for(int i = 0; i < ArraySize(competition); i++)
   {
      string sym = competition[i];
      if(!SymbolSelect(sym, true))
         continue;
      double bid = SymbolInfoDouble(sym, SYMBOL_BID);
      double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
      if(bid <= 0 || ask <= 0)
         continue;
      if(n > 0) tick_data += ",";
      tick_data += StringFormat("{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f}", sym, bid, ask);
      n++;
   }
   if(n > 0)
   {
      string payload = StringFormat("{\"ticks\":[%s]}", tick_data);
      ZmqMsg tick_msg(payload);
      pub_socket.send(tick_msg, false);
   }
}

//+------------------------------------------------------------------+
string SymbolMap(string symbol)
{
   StringReplace(symbol, "/", "");
   return symbol;
}

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES TimeframeMap(string tf)
{
   if(tf == "M15") return PERIOD_M15;
   if(tf == "H1")  return PERIOD_H1;
   if(tf == "H4")  return PERIOD_H4;
   if(tf == "M5")  return PERIOD_M5;
   if(tf == "D1")  return PERIOD_D1;
   return PERIOD_M15;
}

//+------------------------------------------------------------------+
string JsonGet(string json, string key)
{
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos += StringLen(search);
   while(pos < StringLen(json) && (StringGetCharacter(json, pos) == ' ' || StringGetCharacter(json, pos) == '"'))
      pos++;
   int end = pos;
   while(end < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, end);
      if(ch == '"' || ch == ',' || ch == '}') break;
      end++;
   }
   string val = StringSubstr(json, pos, end - pos);
   StringReplace(val, "\"", "");
   return val;
}

//+------------------------------------------------------------------+
bool IsRetryableRetcode(uint retcode)
{
   return retcode == TRADE_RETCODE_REQUOTE
       || retcode == TRADE_RETCODE_PRICE_CHANGED
       || retcode == TRADE_RETCODE_INVALID_PRICE
       || retcode == TRADE_RETCODE_INVALID_STOPS;
}

//+------------------------------------------------------------------+
string BuildError(string message, ulong start_ms)
{
   ulong latency = GetTickCount64() - start_ms;
   return StringFormat("{\"status\":\"error\",\"message\":\"%s\",\"latency_ms\":%d}", message, (int)latency);
}
